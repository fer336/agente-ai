import pytest
from httpx import ASGITransport, AsyncClient

from app.config.settings import Settings, get_settings
from app.main import app
from tests.fixtures.seed_objects import make_chatwoot_payload

_WEBHOOK_SECRET = "correct-secret"
_INBOX_ID = "42"


def _override_settings() -> Settings:
    return Settings(
        chatwoot_webhook_secret=_WEBHOOK_SECRET,
        chatwoot_inbox_id=_INBOX_ID,
        _env_file=None,
    )


@pytest.fixture(autouse=True)
def _override_webhook_settings():
    app.dependency_overrides[get_settings] = _override_settings
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wrong_secret_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/chatwoot/wrong-secret",
            json=make_chatwoot_payload(),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid webhook secret"


async def _post_webhook(payload: dict[str, object]):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/webhooks/chatwoot/{_WEBHOOK_SECRET}", json=payload)


@pytest.mark.asyncio
async def test_wrong_inbox_dropped():
    response = await _post_webhook(make_chatwoot_payload(inbox={"id": 999}))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_private_note_dropped():
    response = await _post_webhook(make_chatwoot_payload(private=True))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_outgoing_message_dropped():
    # Outgoing + agent_bot sender is exactly the mirrored-AI-reply shape from
    # the Etapa 5 outbound mirror (Phase 5) — it must never reach ingestion,
    # otherwise it would flip conversation.mode to "human" (regression guard).
    response = await _post_webhook(
        make_chatwoot_payload(message_type="outgoing", sender={"type": "agent_bot"})
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_incoming_message_forwarded_to_ingestion():
    response = await _post_webhook(make_chatwoot_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


@pytest.mark.asyncio
async def test_valid_message_missing_sender_phone_number_acked_not_500():
    # A payload that passes all four filters (message_created, incoming,
    # non-private, matching inbox) but lacks sender.phone_number is a
    # plausible-but-incomplete Chatwoot payload (e.g. a contact record with
    # no phone populated). It must never crash the handler with an unhandled
    # 500 — Chatwoot retries 5xx responses, which could cause a retry storm.
    # `raise_app_exceptions=False` mirrors real deployed ASGI behavior
    # (uncaught exceptions surface as a 500 response, not a Python
    # exception), matching how the verify agent reproduced the bug.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/chatwoot/{_WEBHOOK_SECRET}",
            json=make_chatwoot_payload(sender={}),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


def test_route_has_openapi_metadata():
    schema = app.openapi()
    operation = schema["paths"]["/webhooks/chatwoot/{secret}"]["post"]

    assert operation["summary"] == "Receive a Chatwoot `message_created` outgoing webhook event"
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
    assert "/webhooks/chatwoot/{secret}" in openapi_json.json()["paths"]
