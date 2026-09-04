from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.gateways import get_messaging_gateway
from app.api.dependencies.repositories import get_conversation_repository
from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_TECHNICAL
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from app.main import app
from tests.fixtures.gateways import make_ingest_message_use_case
from tests.fixtures.seed_objects import (
    make_conversation,
    make_ycloud_payload,
    make_ycloud_tag_change_payload,
)

_WEBHOOK_SECRET = "correct-secret"
_WHATSAPP_NUMBER = "+5491100000001"


def _override_settings() -> Settings:
    return Settings(
        ycloud_webhook_secret=_WEBHOOK_SECRET,
        ycloud_whatsapp_number=_WHATSAPP_NUMBER,
        _env_file=None,
    )


@dataclass
class _IngestFakes:
    """Repositories backing the route-level `IngestMessageUseCase` override.

    Exposed so tests that need to inspect post-request state (task 4.15's
    TRIANGULATE step) can request this fixture by name; tests that only
    care about the HTTP response ignore it.
    """

    message_repository: FakeMessageRepository
    contact_repository: FakeContactRepository
    conversation_repository: FakeConversationRepository


@pytest.fixture(autouse=True)
def _override_webhook_settings():
    app.dependency_overrides[get_settings] = _override_settings

    # `IngestMessageUseCase` is a process-level `@lru_cache`d singleton in
    # production (see `app.api.dependencies.use_cases`), backed by a REAL
    # Postgres session factory and REAL Redis client. Without this
    # override, resolving `Depends(get_ingest_message_use_case)` for every
    # request to this route would build (and cache, for the rest of the
    # test session) that real singleton — these are unit tests and must
    # not depend on live infrastructure.
    message_repository = FakeMessageRepository()
    contact_repository = FakeContactRepository()
    conversation_repository = FakeConversationRepository()
    fake_use_case = make_ingest_message_use_case(
        message_repository=message_repository,
        contact_repository=contact_repository,
        conversation_repository=conversation_repository,
    )
    app.dependency_overrides[get_ingest_message_use_case] = lambda: fake_use_case

    yield _IngestFakes(
        message_repository=message_repository,
        contact_repository=contact_repository,
        conversation_repository=conversation_repository,
    )
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wrong_secret_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/ycloud/wrong-secret",
            json=make_ycloud_payload(),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid webhook secret"


async def _post_webhook(payload: dict[str, object]):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/webhooks/ycloud/{_WEBHOOK_SECRET}", json=payload)


@pytest.mark.asyncio
async def test_wrong_whatsapp_number_dropped():
    response = await _post_webhook(
        make_ycloud_payload(
            whatsappInboundMessage={
                "id": "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5",
                "from": "+5491122334455",
                "to": "+5491199999999",
                "type": "text",
                "text": {"body": "Hola"},
            }
        )
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_non_text_message_type_dropped():
    # Audio (PRD §24.1) and button/interactive replies are recognized but
    # not processed yet — that pipeline doesn't exist in this codebase.
    response = await _post_webhook(
        make_ycloud_payload(
            whatsappInboundMessage={
                "id": "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5",
                "from": "+5491122334455",
                "to": _WHATSAPP_NUMBER,
                "type": "audio",
            }
        )
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_unknown_event_type_dropped():
    # e.g. a delivery-status event, not an inbound message.
    response = await _post_webhook(make_ycloud_payload(type="whatsapp.message.delivered"))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_incoming_message_forwarded_to_ingestion(_override_webhook_settings):
    # TRIANGULATE (task 4.15): asserts the REAL `IngestMessageUseCase` ran
    # end-to-end through the route (not just that the route returned 200) —
    # a contact and a conversation were resolved/created, and the message
    # was actually persisted, proving `webhook.py` really calls
    # `use_case.execute(dto)` rather than just building the DTO and
    # discarding it.
    fakes = _override_webhook_settings

    response = await _post_webhook(make_ycloud_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    contact = await fakes.contact_repository.get_by_phone(PhoneNumber("+5491122334455"))
    assert contact is not None

    conversation = await fakes.conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"

    assert (
        await fakes.message_repository.exists_by_external_id(
            ExternalMessageId("wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5")
        )
        is True
    )


@pytest.mark.asyncio
async def test_existing_conversation_not_duplicated_across_webhook_deliveries(
    _override_webhook_settings,
):
    fakes = _override_webhook_settings
    await fakes.conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="agent")
    )

    response = await _post_webhook(make_ycloud_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    conversation = await fakes.conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_valid_message_missing_sender_phone_number_acked_not_500():
    # A payload that passes the event/message-type/number filters but lacks
    # `whatsappInboundMessage.from` is a plausible-but-incomplete YCloud
    # payload. It must never crash the handler with an unhandled 500 —
    # YCloud retries 5xx responses, which could cause a retry storm.
    # `raise_app_exceptions=False` mirrors real deployed ASGI behavior
    # (uncaught exceptions surface as a 500 response, not a Python
    # exception).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/ycloud/{_WEBHOOK_SECRET}",
            json=make_ycloud_payload(
                whatsappInboundMessage={
                    "id": "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5",
                    "from": "",
                    "to": _WHATSAPP_NUMBER,
                    "type": "text",
                    "text": {"body": "Hola"},
                }
            ),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_message_missing_external_id_acked_not_500():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/ycloud/{_WEBHOOK_SECRET}",
            json=make_ycloud_payload(
                whatsappInboundMessage={
                    "id": "",
                    "from": "+5491122334455",
                    "to": _WHATSAPP_NUMBER,
                    "type": "text",
                    "text": {"body": "Hola"},
                }
            ),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_message_whitespace_only_external_id_acked_not_500():
    # A whitespace-only id is truthy, so it would bypass a falsy-only
    # guard — `ExternalMessageId` itself validates via `.strip()`, not
    # falsiness, so the parser's guard must match that invariant exactly.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/ycloud/{_WEBHOOK_SECRET}",
            json=make_ycloud_payload(
                whatsappInboundMessage={
                    "id": "   ",
                    "from": "+5491122334455",
                    "to": _WHATSAPP_NUMBER,
                    "type": "text",
                    "text": {"body": "Hola"},
                }
            ),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@dataclass
class _TagWebhookFakes:
    messaging_gateway: FakeYCloudMessagingGateway
    conversation_repository: FakeConversationRepository


@pytest.fixture
def _tag_webhook_fakes():
    messaging_gateway = FakeYCloudMessagingGateway()
    conversation_repository = FakeConversationRepository()
    app.dependency_overrides[get_messaging_gateway] = lambda: messaging_gateway
    app.dependency_overrides[get_conversation_repository] = lambda: conversation_repository

    yield _TagWebhookFakes(
        messaging_gateway=messaging_gateway, conversation_repository=conversation_repository
    )

    del app.dependency_overrides[get_messaging_gateway]
    del app.dependency_overrides[get_conversation_repository]


@pytest.mark.asyncio
async def test_tag_humano_removed_resumes_the_bot(_tag_webhook_fakes):
    fakes = _tag_webhook_fakes
    fakes.messaging_gateway.contact_phones["ycloud-contact-1"] = PhoneNumber("+5491122334455")
    await fakes.conversation_repository.save(make_conversation(mode="human", input_state="HUMAN"))

    response = await _post_webhook(
        make_ycloud_tag_change_payload(
            contact_id="ycloud-contact-1", tag_value="Humano", action="REMOVED"
        )
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    conversation = await fakes.conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_tag_humano_added_pauses_the_bot(_tag_webhook_fakes):
    fakes = _tag_webhook_fakes
    fakes.messaging_gateway.contact_phones["ycloud-contact-1"] = PhoneNumber("+5491122334455")
    await fakes.conversation_repository.save(make_conversation(mode="agent"))

    response = await _post_webhook(
        make_ycloud_tag_change_payload(
            contact_id="ycloud-contact-1", tag_value="Humano", action="ADDED"
        )
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    conversation = await fakes.conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "human"
    assert conversation.input_state == "HUMAN"


@pytest.mark.asyncio
async def test_tag_change_with_unrelated_tag_ignored(_tag_webhook_fakes):
    response = await _post_webhook(make_ycloud_tag_change_payload(tag_value="vip"))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_tag_change_for_unresolvable_contact_acked_not_500(_tag_webhook_fakes):
    # `contact_phones` is left empty — `get_contact_phone` returns `None`,
    # exercising the use case's silent no-op path.
    response = await _post_webhook(make_ycloud_tag_change_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


def test_route_has_openapi_metadata():
    schema = app.openapi()
    operation = schema["paths"]["/webhooks/ycloud/{secret}"]["post"]

    assert "whatsapp.inbound_message.received" in operation["summary"]
    assert "contact.attributes_changed" in operation["summary"]
    assert operation["tags"] == ["webhooks"]


@pytest.mark.asyncio
async def test_public_docs_are_disabled_admin_docs_require_a_session():
    """The default `/docs`/`/redoc`/`/openapi.json` are disabled (`app.main`)
    so the API schema — including the `/admin/*` surface — isn't world-
    readable; `/admin/docs`/`/admin/redoc`/`/admin/openapi.json` re-expose
    the same content behind the same admin session auth as the rest of the
    panel (see `app.api.routes.admin_docs`).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404

        assert (await client.get("/admin/docs")).status_code == 401
        assert (await client.get("/admin/openapi.json")).status_code == 401

        # `_override_settings()` (the autouse fixture above) leaves
        # `admin_session_secret` at its default `""` — sign with the same
        # value so the session verifies against it.
        token, csrf = create_session_token(
            "admin-1", "tech1", ADMIN_TECHNICAL, "", 3600, now=datetime.now(UTC)
        )
        cookies = {"admin_session": token, "admin_csrf": csrf}
        admin_docs = await client.get("/admin/docs", cookies=cookies)
        admin_openapi = await client.get("/admin/openapi.json", cookies=cookies)

    assert admin_docs.status_code == 200
    assert admin_openapi.status_code == 200
    assert "/webhooks/ycloud/{secret}" in admin_openapi.json()["paths"]
