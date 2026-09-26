import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.gateways import get_chatwoot_gateway, get_messaging_gateway
from app.api.dependencies.repositories import (
    get_chatwoot_mapping_repository,
    get_committing_conversation_repository,
)
from app.config.settings import Settings, get_settings
from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from app.main import app
from tests.fixtures.seed_objects import make_conversation

_WEBHOOK_SECRET = "correct-chatwoot-secret"


def _override_settings() -> Settings:
    return Settings(chatwoot_webhook_secret=_WEBHOOK_SECRET, _env_file=None)


@pytest.fixture(autouse=True)
async def _fakes():
    app.dependency_overrides[get_settings] = _override_settings

    messaging_gateway = FakeYCloudMessagingGateway()
    chatwoot_gateway = FakeChatwootGateway()
    conversation_repository = FakeConversationRepository()
    mapping_repository = FakeChatwootMappingRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="human")
    )
    await mapping_repository.save(
        ChatwootConversationMapping(
            conversation_id="ycloud-+5491122334455",
            chatwoot_contact_id="1",
            chatwoot_conversation_id="99",
        )
    )

    app.dependency_overrides[get_messaging_gateway] = lambda: messaging_gateway
    app.dependency_overrides[get_chatwoot_gateway] = lambda: chatwoot_gateway
    app.dependency_overrides[get_committing_conversation_repository] = (
        lambda: conversation_repository
    )
    app.dependency_overrides[get_chatwoot_mapping_repository] = lambda: mapping_repository

    yield messaging_gateway, chatwoot_gateway, conversation_repository
    app.dependency_overrides.clear()


async def _post_webhook(payload: dict[str, object], secret: str = _WEBHOOK_SECRET):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/webhooks/chatwoot/{secret}", json=payload)


@pytest.mark.asyncio
async def test_wrong_secret_rejected():
    response = await _post_webhook(
        {"event": "message_created", "message_type": "outgoing"}, secret="wrong-secret"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid webhook secret"


@pytest.mark.asyncio
async def test_staff_reply_is_forwarded_to_whatsapp(_fakes):
    messaging_gateway, _, _ = _fakes

    response = await _post_webhook(
        {
            "event": "message_created",
            "message_type": "outgoing",
            "content": "Hola, te confirmo el turno",
            "conversation": {"id": 99},
            "sender": {"id": 5, "type": "user"},
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Hola, te confirmo el turno")
    ]


@pytest.mark.asyncio
async def test_administracion_reply_is_formatted_before_forwarding(_fakes):
    messaging_gateway, chatwoot_gateway, _ = _fakes
    await chatwoot_gateway.assign_administracion("99")

    response = await _post_webhook(
        {
            "event": "message_created",
            "message_type": "outgoing",
            "content": "Te atiendo personalmente",
            "conversation": {"id": 99},
            "sender": {"id": 5, "type": "user"},
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Administracion\n| Te atiendo personalmente")
    ]


@pytest.mark.asyncio
async def test_staff_reply_pauses_the_bot_before_forwarding_and_syncs_the_label(_fakes):
    messaging_gateway, chatwoot_gateway, conversation_repository = _fakes
    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    conversation.mode = "agent"
    conversation.input_state = "FREE_INPUT"
    await conversation_repository.save(conversation)

    response = await _post_webhook(
        {
            "event": "message_created",
            "message_type": "outgoing",
            "content": "Te atiendo personalmente",
            "conversation": {"id": 99},
            "sender": {"id": 5, "type": "user"},
        }
    )

    assert response.status_code == 200
    updated = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert updated is not None
    assert updated.mode == "human"
    assert updated.input_state == "HUMAN"
    assert chatwoot_gateway.labels_by_conversation == {"99": "administracion"}
    # This reply did not carry `administracion` before the safety handoff;
    # it pauses the bot but must retain its original patient-facing content.
    assert messaging_gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Te atiendo personalmente")
    ]


@pytest.mark.asyncio
async def test_bots_own_mirrored_message_is_ignored_not_forwarded(_fakes):
    messaging_gateway, _, _ = _fakes

    response = await _post_webhook(
        {
            "event": "message_created",
            "message_type": "outgoing",
            "content": "¡Hola! ¿En qué te ayudo?",
            "conversation": {"id": 99},
            "sender": {"id": 1, "type": "agent_bot"},
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_resolved_conversation_flips_mode_back_to_agent(_fakes):
    _, chatwoot_gateway, conversation_repository = _fakes

    response = await _post_webhook(
        {"event": "conversation_status_changed", "id": 99, "status": "resolved"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"
    assert chatwoot_gateway.labels_by_conversation == {"99": "agente"}


@pytest.mark.asyncio
async def test_non_resolved_status_change_is_ignored(_fakes):
    _, _, conversation_repository = _fakes

    response = await _post_webhook(
        {"event": "conversation_status_changed", "id": 99, "status": "pending"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "human"


@pytest.mark.asyncio
async def test_administracion_label_pauses_the_bot(_fakes):
    _, _, conversation_repository = _fakes
    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    conversation.mode = "agent"
    conversation.input_state = "FREE_INPUT"
    await conversation_repository.save(conversation)

    response = await _post_webhook(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {
                    "label_list": {
                        "previous_value": ["agente"],
                        "current_value": ["administracion"],
                    }
                }
            ],
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    updated = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert updated is not None
    assert updated.mode == "human"
    assert updated.input_state == "HUMAN"


@pytest.mark.asyncio
async def test_agente_label_reactivates_the_bot(_fakes):
    _, chatwoot_gateway, conversation_repository = _fakes

    response = await _post_webhook(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {
                    "label_list": {
                        "previous_value": ["administracion"],
                        "current_value": ["agente"],
                    }
                }
            ],
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    updated = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert updated is not None
    assert updated.mode == "agent"
    assert updated.input_state == "FREE_INPUT"
    assert chatwoot_gateway.labels_by_conversation == {"99": "agente"}


@pytest.mark.asyncio
async def test_unrelated_conversation_update_is_ignored(_fakes):
    response = await _post_webhook(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {"assignee_id": {"previous_value": None, "current_value": 5}}
            ],
        }
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored():
    response = await _post_webhook({"event": "contact_created"})

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
