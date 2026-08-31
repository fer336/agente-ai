"""Unit tests for `IngestMessageUseCase` (Etapa 4 Phase 4).

Uses only fakes — `FakeMessageRepository`/`FakeContactRepository`/
`FakeConversationRepository`/`FakeAgentInvoker`/`InMemoryFakeRedis` — per
the design doc's Testing Strategy table. See `_build_use_case()` for how
the use case's `repositories_provider` abstraction (a single async-context-
manager callable bundling all three repositories) is satisfied by fakes
with no session/transaction lifecycle, vs. the real SQLAlchemy-session-
backed provider used in production DI
(`app.api.dependencies.use_cases.get_ingest_message_use_case`).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.application.messages.ingest_message import IngestMessageUseCase, MessageRepositories
from app.domain.entities.contact import Contact
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.redis.debounce import DebounceTracker
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agent_invoker,
    make_contact_repository,
    make_conversation_repository,
    make_media_processing_job_repository,
    make_message_repository,
)
from tests.fixtures.seed_objects import make_conversation, make_message

_DEBOUNCE_SECONDS = 6


def _make_dto(
    external_message_id: str = "wamid.1",
    from_phone: str = "+5491122334455",
    text: str = "Hola, quiero agendar un turno",
    button_payload: str | None = None,
) -> InboundMessageDTO:
    return InboundMessageDTO(
        external_message_id=external_message_id,
        from_phone=PhoneNumber(from_phone),
        text=text,
        button_payload=button_payload,
    )


def _make_audio_dto(
    external_message_id: str = "wamid.audio-1",
    from_phone: str = "+5491122334455",
    media_id: str = "media-1",
    media_mime_type: str = "audio/ogg",
    media_sha256: str | None = None,
) -> InboundMessageDTO:
    return InboundMessageDTO(
        external_message_id=external_message_id,
        from_phone=PhoneNumber(from_phone),
        text="",
        button_payload=None,
        message_type="audio",
        media_id=media_id,
        media_mime_type=media_mime_type,
        media_sha256=media_sha256,
    )


def _build_use_case(
    message_repository=None,
    contact_repository=None,
    conversation_repository=None,
    media_processing_job_repository=None,
    redis_client=None,
    debounce_tracker=None,
    agent_invoker=None,
    debounce_seconds: int = _DEBOUNCE_SECONDS,
    audio_rate_limit_per_minute: int = 0,
) -> IngestMessageUseCase:
    message_repository = (
        message_repository if message_repository is not None else make_message_repository()
    )
    contact_repository = (
        contact_repository if contact_repository is not None else make_contact_repository()
    )
    conversation_repository = (
        conversation_repository
        if conversation_repository is not None
        else make_conversation_repository()
    )
    media_processing_job_repository = (
        media_processing_job_repository
        if media_processing_job_repository is not None
        else make_media_processing_job_repository()
    )
    redis_client = redis_client if redis_client is not None else InMemoryFakeRedis()
    debounce_tracker = (
        debounce_tracker
        if debounce_tracker is not None
        else DebounceTracker(redis_client, debounce_seconds)
    )
    agent_invoker = agent_invoker if agent_invoker is not None else make_agent_invoker()

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[MessageRepositories]:
        yield MessageRepositories(
            messages=message_repository,
            contacts=contact_repository,
            conversations=conversation_repository,
            media_processing_jobs=media_processing_job_repository,
        )

    return IngestMessageUseCase(
        repositories_provider=repositories_provider,
        debounce_tracker=debounce_tracker,
        redis_client=redis_client,
        agent_invoker=agent_invoker,
        debounce_seconds=debounce_seconds,
        audio_rate_limit_per_minute=audio_rate_limit_per_minute,
    )


@pytest.mark.asyncio
async def test_duplicate_source_id_ignored():
    message_repository = make_message_repository()
    await message_repository.save(make_message(external_message_id="wamid.1"))
    contact_repository = make_contact_repository()
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(
        message_repository=message_repository,
        contact_repository=contact_repository,
        agent_invoker=agent_invoker,
    )

    await use_case.execute(_make_dto(external_message_id="wamid.1"))

    # The pipeline halted before contact resolution — proves it short-
    # circuited on the duplicate rather than merely tolerating it.
    assert await contact_repository.get_by_phone(PhoneNumber("+5491122334455")) is None
    assert agent_invoker.calls == []


@pytest.mark.asyncio
async def test_new_contact_created():
    contact_repository = make_contact_repository()
    use_case = _build_use_case(contact_repository=contact_repository)

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    contact = await contact_repository.get_by_phone(PhoneNumber("+5491122334455"))
    assert contact is not None
    assert str(contact.phone) == "+5491122334455"


@pytest.mark.asyncio
async def test_existing_contact_resolved_not_duplicated():
    contact_repository = make_contact_repository()
    existing = Contact(id="contact-existing", phone=PhoneNumber("+5491122334455"), patient_id=None)
    await contact_repository.save(existing)
    use_case = _build_use_case(contact_repository=contact_repository)

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    matching = [
        c
        for c in contact_repository._contacts_by_id.values()
        if str(c.phone) == "+5491122334455"
    ]
    assert matching == [existing]


@pytest.mark.asyncio
async def test_new_conversation_created_with_ycloud_prefixed_id_and_agent_mode():
    conversation_repository = make_conversation_repository()
    use_case = _build_use_case(conversation_repository=conversation_repository)

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_existing_conversation_resolved_not_duplicated():
    conversation_repository = make_conversation_repository()
    existing = make_conversation(id_="ycloud-+5491122334455", mode="agent")
    await conversation_repository.save(existing)
    use_case = _build_use_case(conversation_repository=conversation_repository)

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    assert len(conversation_repository._conversations_by_id) == 1
    fetched = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert fetched == existing


@pytest.mark.asyncio
async def test_human_mode_blocks_handoff():
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="human"))
    redis_client = InMemoryFakeRedis()
    use_case = _build_use_case(
        conversation_repository=conversation_repository, redis_client=redis_client
    )

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    # No debounce key was ever touched — the human-mode gate short-circuits
    # BEFORE debounce/lock/seam, per spec's "Human-Mode Pause Gate".
    assert await redis_client.get("debounce:conversation:ycloud-+5491122334455") is None


@pytest.mark.asyncio
async def test_agent_mode_proceeds_to_debounce():
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    redis_client = InMemoryFakeRedis()
    use_case = _build_use_case(
        conversation_repository=conversation_repository, redis_client=redis_client
    )

    await use_case.execute(_make_dto(from_phone="+5491122334455"))

    assert await redis_client.get("debounce:conversation:ycloud-+5491122334455") is not None


@pytest.mark.asyncio
async def test_multiple_messages_grouped_into_one_handoff():
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(agent_invoker=agent_invoker, debounce_seconds=0.05)

    await use_case.execute(
        _make_dto(external_message_id="wamid.1", from_phone="+5491122334455", text="Hola")
    )
    await asyncio.sleep(0.02)
    await use_case.execute(
        _make_dto(
            external_message_id="wamid.2", from_phone="+5491122334455", text="quiero un turno"
        )
    )
    await asyncio.sleep(0.02)
    await use_case.execute(
        _make_dto(
            external_message_id="wamid.3", from_phone="+5491122334455", text="para mañana"
        )
    )
    await asyncio.sleep(0.15)

    assert len(agent_invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = agent_invoker.calls[0]
    assert conversation_id == ConversationId("ycloud-+5491122334455")
    assert len(message_ids) == 3
    # Arrival order is proven by the joined text, not just the count.
    assert user_message == "Hola\nquiero un turno\npara mañana"
    assert button_payload is None


@pytest.mark.asyncio
async def test_grouped_messages_use_the_last_non_null_button_payload():
    # PRD.md §6: a deliberate button tap is a terminal action that must
    # take priority over any free text debounced alongside it.
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(agent_invoker=agent_invoker, debounce_seconds=0.05)

    await use_case.execute(
        _make_dto(external_message_id="wamid.1", from_phone="+5491122334455", text="Hola")
    )
    await asyncio.sleep(0.02)
    await use_case.execute(
        _make_dto(
            external_message_id="wamid.2",
            from_phone="+5491122334455",
            text="✅ Confirmar",
            button_payload="CONFIRM_APPOINTMENT",
        )
    )
    await asyncio.sleep(0.15)

    assert len(agent_invoker.calls) == 1
    _, _, _, button_payload = agent_invoker.calls[0]
    assert button_payload == "CONFIRM_APPOINTMENT"


@pytest.mark.asyncio
async def test_single_message_still_produces_valid_dto():
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(agent_invoker=agent_invoker, debounce_seconds=0.05)

    await use_case.execute(
        _make_dto(external_message_id="wamid.1", from_phone="+5491100000022", text="Hola sola")
    )
    await asyncio.sleep(0.15)

    assert len(agent_invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = agent_invoker.calls[0]
    assert conversation_id == ConversationId("ycloud-+5491100000022")
    assert len(message_ids) == 1
    assert user_message == "Hola sola"
    assert button_payload is None


class _YieldingContactRepository:
    """Wraps a `FakeContactRepository`, yielding control to the event loop
    right after `get_by_phone` resolves but before returning.

    This forces two concurrently-scheduled `execute()` calls to interleave
    at exactly the point a real, non-transactional Postgres get-then-insert
    would under true concurrent request handling — `contacts.phone` has NO
    DB-level unique constraint (confirmed in the Etapa 4 PR1 verify report,
    id 3979), so this scenario is a real, reachable production race, not a
    hypothetical one. Without a forced yield here, two `asyncio.gather`'d
    calls against a plain in-memory fake would never actually interleave,
    since neither coroutine has any other true suspension point before
    `save()` — this double would be pointless against a repository that
    already does real (yielding) I/O, like the real SQLAlchemy adapter.
    """

    def __init__(self, inner):
        self._inner = inner

    async def get_by_phone(self, phone):
        result = await self._inner.get_by_phone(phone)
        await asyncio.sleep(0)
        return result

    async def save(self, contact):
        await self._inner.save(contact)


@pytest.mark.asyncio
async def test_concurrent_ingestion_for_a_new_phone_can_race_and_create_duplicate_contacts():
    """Documents a known, accepted limitation flagged by the Etapa 4 PR1
    verify report (id 3979, INFO finding): `IngestMessageUseCase` does not
    add any application-level locking around contact resolution — only the
    per-conversation Redis lock exists, and it is acquired much later,
    around the debounce-fire step, never around contact creation. Two truly
    concurrent webhook deliveries for a brand-new phone number can each
    resolve `get_by_phone -> None` before either has called `save`,
    producing two distinct Contact rows for the same phone.

    This test is NOT asserting desired behavior — it is a regression
    baseline capturing the current, known-racy behavior, so a future fix
    (e.g. a DB unique index + upsert-on-conflict) has a test to flip from
    "duplicates possible" to "duplicates prevented" instead of silently
    fixing an undocumented gap.
    """
    shared_fake = make_contact_repository()
    racy_repository = _YieldingContactRepository(shared_fake)
    use_case = _build_use_case(contact_repository=racy_repository)

    await asyncio.gather(
        use_case.execute(
            _make_dto(
                external_message_id="wamid.race-1",
                from_phone="+5491100000099",
            )
        ),
        use_case.execute(
            _make_dto(
                external_message_id="wamid.race-2",
                from_phone="+5491100000099",
            )
        ),
    )

    matching = [
        c for c in shared_fake._contacts_by_id.values() if str(c.phone) == "+5491100000099"
    ]
    assert len(matching) == 2, (
        "expected the documented race to produce 2 duplicate Contact rows for the "
        "same phone — if this now produces 1, the race has been fixed and this test "
        "should be rewritten to assert the fix instead of the known limitation"
    )


@pytest.mark.asyncio
async def test_audio_message_is_persisted_with_media_metadata_and_no_debounce():
    message_repository = make_message_repository()
    redis_client = InMemoryFakeRedis()
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(
        message_repository=message_repository,
        redis_client=redis_client,
        agent_invoker=agent_invoker,
    )

    await use_case.execute(
        _make_audio_dto(media_id="media-1", media_mime_type="audio/ogg", media_sha256="abc123")
    )

    messages = list(message_repository._messages_by_id.values())
    assert len(messages) == 1
    message = messages[0]
    assert message.message_type == "audio"
    assert message.text == ""
    assert message.media_id == "media-1"
    assert message.media_mime_type == "audio/ogg"
    assert message.media_sha256 == "abc123"
    assert message.media_status == "pending"
    # No debounce/agent-invocation yet — there is no transcript.
    assert agent_invoker.calls == []
    assert (
        await redis_client.get("debounce:conversation:ycloud-+5491122334455") is None
    )


@pytest.mark.asyncio
async def test_audio_message_creates_a_pending_media_processing_job():
    media_processing_job_repository = make_media_processing_job_repository()
    use_case = _build_use_case(media_processing_job_repository=media_processing_job_repository)

    await use_case.execute(_make_audio_dto(media_id="media-1", media_mime_type="audio/ogg"))

    pending = await media_processing_job_repository.list_pending(limit=10)
    assert len(pending) == 1
    assert pending[0].media_id == "media-1"
    assert pending[0].media_mime_type == "audio/ogg"


@pytest.mark.asyncio
async def test_duplicate_audio_external_id_is_ignored():
    message_repository = make_message_repository()
    media_processing_job_repository = make_media_processing_job_repository()
    use_case = _build_use_case(
        message_repository=message_repository,
        media_processing_job_repository=media_processing_job_repository,
    )
    await use_case.execute(_make_audio_dto(external_message_id="wamid.audio-dup"))

    await use_case.execute(_make_audio_dto(external_message_id="wamid.audio-dup"))

    assert len(message_repository._messages_by_id) == 1
    assert len(await media_processing_job_repository.list_pending(limit=10)) == 1


@pytest.mark.asyncio
async def test_audio_message_persisted_even_when_conversation_is_human_mode():
    # A human in the shared inbox still benefits from the eventual
    # transcript — only forwarding to the agent is gated on mode, and only
    # once a transcript exists (see resume_after_transcription tests below).
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="human"))
    message_repository = make_message_repository()
    use_case = _build_use_case(
        conversation_repository=conversation_repository, message_repository=message_repository
    )

    await use_case.execute(_make_audio_dto())

    assert len(message_repository._messages_by_id) == 1


@pytest.mark.asyncio
async def test_audio_rate_limit_drops_message_past_the_configured_threshold():
    message_repository = make_message_repository()
    media_processing_job_repository = make_media_processing_job_repository()
    use_case = _build_use_case(
        message_repository=message_repository,
        media_processing_job_repository=media_processing_job_repository,
        audio_rate_limit_per_minute=2,
    )

    await use_case.execute(_make_audio_dto(external_message_id="wamid.audio-1"))
    await use_case.execute(_make_audio_dto(external_message_id="wamid.audio-2"))
    await use_case.execute(_make_audio_dto(external_message_id="wamid.audio-3"))

    assert len(message_repository._messages_by_id) == 2
    assert len(await media_processing_job_repository.list_pending(limit=10)) == 2


@pytest.mark.asyncio
async def test_audio_rate_limit_disabled_by_default():
    message_repository = make_message_repository()
    use_case = _build_use_case(message_repository=message_repository)

    for i in range(10):
        await use_case.execute(_make_audio_dto(external_message_id=f"wamid.audio-{i}"))

    assert len(message_repository._messages_by_id) == 10


@pytest.mark.asyncio
async def test_resume_after_transcription_schedules_debounce_with_no_button_payload():
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    agent_invoker = make_agent_invoker()
    use_case = _build_use_case(
        conversation_repository=conversation_repository,
        agent_invoker=agent_invoker,
        debounce_seconds=0.05,
    )

    await use_case.resume_after_transcription(
        ConversationId("ycloud-+5491122334455"), "msg-audio-1", "hola quiero un turno"
    )
    await asyncio.sleep(0.15)

    assert len(agent_invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = agent_invoker.calls[0]
    assert conversation_id == ConversationId("ycloud-+5491122334455")
    assert message_ids == ["msg-audio-1"]
    assert user_message == "hola quiero un turno"
    assert button_payload is None


@pytest.mark.asyncio
async def test_resume_after_transcription_does_not_forward_when_conversation_is_human():
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="human"))
    agent_invoker = make_agent_invoker()
    redis_client = InMemoryFakeRedis()
    use_case = _build_use_case(
        conversation_repository=conversation_repository,
        agent_invoker=agent_invoker,
        redis_client=redis_client,
        debounce_seconds=0.05,
    )

    await use_case.resume_after_transcription(
        ConversationId("ycloud-+5491122334455"), "msg-audio-1", "hola quiero un turno"
    )
    await asyncio.sleep(0.1)

    assert agent_invoker.calls == []
    assert await redis_client.get("debounce:conversation:ycloud-+5491122334455") is None
