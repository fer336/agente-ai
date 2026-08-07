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
from tests.fixtures.seed_objects import make_chatwoot_payload, make_conversation

_WEBHOOK_SECRET = "correct-secret"
_INBOX_ID = "42"


def _override_settings() -> Settings:
    return Settings(
        chatwoot_webhook_secret=_WEBHOOK_SECRET,
        chatwoot_inbox_id=_INBOX_ID,
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
async def test_mirrored_agent_bot_message_never_flips_mode_to_human(_override_webhook_settings):
    # Phase 5 mode-flip regression test (task 5.8). Necessity check, made
    # explicit rather than assumed: `_passes_filters()` (Phase 2) already
    # drops EVERY payload with `message_type != "incoming"` before
    # `IngestMessageUseCase` ever runs — an outgoing Chatwoot event (our
    # own `ChatwootConversationGateway.mirror_message` write, OR a real
    # human agent's reply typed in Chatwoot) can NEVER reach the ingestion
    # pipeline at all, regardless of `sender.type`. This test therefore
    # proves a structural guarantee that already existed since PR2/PR4 —
    # it is NOT closing a live gap discovered in this phase. Separately:
    # grepping the whole `app/` tree confirms `conversation.mode` is only
    # ever WRITTEN as `"agent"` (at conversation creation) — there is no
    # code path anywhere in this codebase, in this etapa, that sets it to
    # `"human"` at all. "Real human agent reply flips mode to human" logic
    # does not exist yet; per the spec's own "Out of Scope" section, that
    # behavior is deferred to a later etapa (Etapa 5/10), not Etapa 4.
    fakes = _override_webhook_settings
    await fakes.conversation_repository.save(make_conversation(id_="chatwoot-100", mode="agent"))

    response = await _post_webhook(
        make_chatwoot_payload(message_type="outgoing", sender={"type": "agent_bot"})
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}

    conversation = await fakes.conversation_repository.get_by_id(ConversationId("chatwoot-100"))
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_valid_incoming_message_forwarded_to_ingestion(_override_webhook_settings):
    # TRIANGULATE (task 4.15): asserts the REAL `IngestMessageUseCase` ran
    # end-to-end through the route (not just that the route returned 200) —
    # a contact and a conversation were resolved/created, and the message
    # was actually persisted, proving `webhook.py` really calls
    # `use_case.execute(dto)` rather than just building the DTO and
    # discarding it (Phase 2's stub behavior, which this replaces).
    fakes = _override_webhook_settings

    response = await _post_webhook(make_chatwoot_payload())

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}

    contact = await fakes.contact_repository.get_by_phone(PhoneNumber("+5491122334455"))
    assert contact is not None

    conversation = await fakes.conversation_repository.get_by_id(ConversationId("chatwoot-100"))
    assert conversation is not None
    assert conversation.mode == "agent"

    assert (
        await fakes.message_repository.exists_by_external_id(
            ExternalMessageId("wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5")
        )
        is True
    )


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


@pytest.mark.asyncio
async def test_valid_message_missing_source_id_acked_not_500():
    # A payload that passes all four filters (message_created, incoming,
    # non-private, matching inbox) and has a valid sender.phone_number but
    # lacks source_id is a plausible-but-incomplete Chatwoot payload. It
    # must never crash the handler with an unhandled 500 — Chatwoot retries
    # 5xx responses, which could cause a retry storm. Mirrors
    # `test_valid_message_missing_sender_phone_number_acked_not_500` above,
    # extended to cover the sibling `source_id` field that
    # `ExternalMessageId` also rejects when empty.
    # `raise_app_exceptions=False` mirrors real deployed ASGI behavior
    # (uncaught exceptions surface as a 500 response, not a Python
    # exception).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/chatwoot/{_WEBHOOK_SECRET}",
            json=make_chatwoot_payload(source_id=""),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_message_whitespace_only_source_id_acked_not_500():
    # A whitespace-only `source_id` (e.g. "   ") is truthy, so it bypassed
    # the falsy-only guard added by the previous corrective commit and
    # reached `ExternalMessageId(dto.external_message_id)` at the top of
    # `IngestMessageUseCase.execute()` — which is NOT wrapped by the
    # route's try/except (that only wraps `to_inbound_message_dto()`) —
    # producing an unhandled 500. `ExternalMessageId` itself validates via
    # `.strip()`, not falsiness, so the guard must match that invariant
    # exactly. `raise_app_exceptions=False` mirrors real deployed ASGI
    # behavior (uncaught exceptions surface as a 500 response).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/chatwoot/{_WEBHOOK_SECRET}",
            json=make_chatwoot_payload(source_id="   "),
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_valid_message_whitespace_only_sender_phone_number_acked_not_500():
    # Sibling regression guard for `sender.phone_number`: a whitespace-only
    # value is truthy, so it bypasses the falsy-only guard too. Unlike
    # `source_id`, `PhoneNumber(self.sender.phone_number)` is constructed
    # inside `to_inbound_message_dto()` itself (still inside the route's
    # try/except), so this case was never actually reachable as a 500 —
    # `PhoneNumber`'s own format validation (must start with "+") already
    # rejects it there. This test locks in that existing safety after the
    # guard was normalized to `.strip()` for defense-in-depth.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/webhooks/chatwoot/{_WEBHOOK_SECRET}",
            json=make_chatwoot_payload(sender={"phone_number": "   "}),
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
