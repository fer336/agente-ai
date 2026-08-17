from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.config.settings import Settings, get_settings
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.main import app
from tests.fixtures.gateways import make_ingest_message_use_case
from tests.fixtures.seed_objects import make_conversation, make_ycloud_payload

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
    response = await _post_webhook(
        make_ycloud_payload(type="whatsapp.message.delivered")
    )

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


def test_route_has_openapi_metadata():
    schema = app.openapi()
    operation = schema["paths"]["/webhooks/ycloud/{secret}"]["post"]

    assert (
        operation["summary"]
        == "Receive a YCloud `whatsapp.inbound_message.received` webhook event"
    )
    assert operation["tags"] == ["webhooks"]


@pytest.mark.asyncio
async def test_docs_and_redoc_and_openapi_json_still_reachable():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        redoc = await client.get("/redoc")
        openapi_json = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert redoc.status_code == 200
    assert openapi_json.status_code == 200
    assert "/webhooks/ycloud/{secret}" in openapi_json.json()["paths"]
