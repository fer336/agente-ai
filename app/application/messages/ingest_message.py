import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from redis.asyncio import Redis

from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.entities.media_processing_job import PENDING as JOB_PENDING
from app.domain.entities.media_processing_job import MediaProcessingJob
from app.domain.entities.message import MEDIA_PENDING, Message
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.media_processing_job_repository import MediaProcessingJobRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.redis.debounce import DebounceTracker
from app.infrastructure.redis.lock import redis_lock

logger = logging.getLogger(__name__)

#: Redis key prefix for the per-conversation-per-minute audio counter
#: (PRD.md §24.3/§68 `AUDIO_RATE_LIMIT_PER_CONVERSATION_PER_MINUTE`).
_AUDIO_RATE_LIMIT_KEY_PREFIX = "audio_rate_limit:conversation:"
_AUDIO_RATE_LIMIT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class MessageRepositories:
    """Bundles the repositories one `IngestMessageUseCase` unit of work needs."""

    messages: MessageRepository
    contacts: ContactRepository
    conversations: ConversationRepository
    media_processing_jobs: MediaProcessingJobRepository


# A zero-arg async context manager factory yielding a fresh `MessageRepositories`
# for one unit of work. See `IngestMessageUseCase`'s docstring for why this
# indirection exists instead of injecting bound repository instances directly.
RepositoriesProvider = Callable[[], AbstractAsyncContextManager[MessageRepositories]]


class IngestMessageUseCase:
    """Orchestrates Etapa 4's inbound pipeline (design doc's Data Flow):

    dedupe -> resolve-or-create contact -> resolve-or-create conversation ->
    persist message -> human-mode gate -> debounce -> lock -> Etapa 5 seam.

    **Lifetime is a process-level singleton**, not a per-request object (see
    `app.api.dependencies.use_cases.get_ingest_message_use_case`). The
    per-conversation debounce/grouping state below (`_pending_messages`,
    `_background_tasks`) must persist across HTTP requests for the same
    running process — a new instance per request would silently reset the
    accumulator on every message, breaking grouping entirely. Because of
    this, `repositories_provider` is a factory that opens its OWN
    short-lived unit of work (e.g. a fresh SQLAlchemy session) on every
    call — both for the synchronous `execute()` path and for the deferred
    `_debounce_and_process()` step, which runs well after the originating
    HTTP request/response cycle has already ended. Reusing a FastAPI
    request-scoped session here would use an already-closed session by the
    time the debounce window elapses.
    """

    def __init__(
        self,
        repositories_provider: RepositoriesProvider,
        debounce_tracker: DebounceTracker,
        redis_client: Redis,
        agent_invoker: AgentInvoker,
        debounce_seconds: int,
        audio_rate_limit_per_minute: int = 0,
    ) -> None:
        self._repositories_provider = repositories_provider
        self._debounce_tracker = debounce_tracker
        self._redis_client = redis_client
        self._agent_invoker = agent_invoker
        self._debounce_seconds = debounce_seconds
        #: PRD.md §24.3's per-conversation audio rate limit. `0` (the
        #: default) disables the check entirely — every existing caller
        #: that builds this use case without the new parameter (tests,
        #: pre-audio DI wiring) keeps its previous, unlimited behavior.
        self._audio_rate_limit_per_minute = audio_rate_limit_per_minute
        # Per-conversation accumulator of (message_id, text, button_payload)
        # tuples awaiting grouping into one Etapa-5 handoff. In-process
        # only — see the class docstring's singleton-lifetime note and the
        # design's "Debounce trigger mechanism" ADR (no ARQ/durable queue
        # this etapa).
        self._pending_messages: dict[str, list[tuple[str, str, str | None]]] = {}
        # Strong references to in-flight background tasks: asyncio only
        # keeps a WEAK reference to a task created via `create_task()`, so
        # without this set a task can be garbage-collected mid-flight.
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def execute(self, dto: InboundMessageDTO) -> None:
        external_message_id = ExternalMessageId(dto.external_message_id)
        async with self._repositories_provider() as repositories:
            if await repositories.messages.exists_by_external_id(external_message_id):
                return

            contact = await self._resolve_or_create_contact(repositories.contacts, dto.from_phone)
            conversation = await self._resolve_or_create_conversation(
                repositories.conversations, dto.from_phone, contact.id
            )
            conversation_key = str(conversation.id)

            if dto.message_type == "audio":
                if await self._audio_rate_limit_exceeded(conversation_key):
                    logger.warning(
                        "ingest_message.audio_rate_limit_exceeded conversation=%s",
                        conversation_key,
                    )
                    return
                await self._ingest_audio_message(
                    repositories, dto, conversation, external_message_id
                )
                return

            message = Message(
                id=str(uuid4()),
                conversation_id=conversation.id,
                external_message_id=external_message_id,
                direction="inbound",
                text=dto.text,
                created_at=datetime.now(UTC),
            )
            await repositories.messages.save(message)
            conversation_mode = conversation.mode

        if conversation_mode == "human":
            # Human-Mode Pause Gate (spec): short-circuit BEFORE debounce/
            # lock/seam. The message above is still persisted — only the
            # handoff to the Etapa 5 seam is skipped.
            return

        await self._schedule_processing(
            conversation_key, message.id, message.text, dto.button_payload
        )

    async def _ingest_audio_message(
        self,
        repositories: MessageRepositories,
        dto: InboundMessageDTO,
        conversation: Conversation,
        external_message_id: ExternalMessageId,
    ) -> None:
        """Etapa 4/9.1's audio branch (PRD.md §24.1): persists the message's
        media metadata and creates a `MediaProcessingJob`, then returns
        immediately — WITHOUT touching debounce/lock/agent-invocation, since
        there is no transcript yet. The message is persisted regardless of
        `conversation.mode` (a human in the shared inbox needs the
        transcript too, once it exists) — only the eventual
        `resume_after_transcription` forwarding step re-checks `mode`,
        mirroring the text path's own human-mode gate.
        """
        now = datetime.now(UTC)
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            external_message_id=external_message_id,
            direction="inbound",
            text="",
            created_at=now,
            message_type="audio",
            media_id=dto.media_id,
            media_mime_type=dto.media_mime_type,
            media_sha256=dto.media_sha256,
            media_status=MEDIA_PENDING,
            inbound_received_at=now,
            transcription_status=MEDIA_PENDING,
        )
        await repositories.messages.save(message)

        job = MediaProcessingJob(
            id=str(uuid4()),
            message_id=message.id,
            status=JOB_PENDING,
            media_id=dto.media_id or "",
            media_mime_type=dto.media_mime_type or "",
            attempts=0,
        )
        await repositories.media_processing_jobs.save(job)

    async def _audio_rate_limit_exceeded(self, conversation_key: str) -> bool:
        if self._audio_rate_limit_per_minute <= 0:
            return False
        key = f"{_AUDIO_RATE_LIMIT_KEY_PREFIX}{conversation_key}"
        count = await self._redis_client.incr(key)
        if count == 1:
            await self._redis_client.expire(key, _AUDIO_RATE_LIMIT_WINDOW_SECONDS)
        return count > self._audio_rate_limit_per_minute

    async def resume_after_transcription(
        self, conversation_id: ConversationId, message_id: str, text: str
    ) -> None:
        """`TranscribeAudioUseCase`'s success path: feeds the transcript
        through the EXACT SAME debounce/lock/agent-invocation machinery a
        typed message already uses (PRD.md §24.1's "Normalizar texto ->
        LangGraph"). `button_payload` is always `None` here — a
        transcript never carries one (PRD.md §24.2/§72: audio must never
        itself confirm a sensitive operation or advance an interactive
        selection; only a real button payload can, and this method has no
        such payload to give it).

        Re-checks `conversation.mode` at call time rather than trusting
        whatever it was when the audio first arrived — mode may have
        flipped to `human` while transcription was in flight, and PRD.md
        §24.2's "Audio en HUMAN -> no se procesa" must still hold.
        """
        conversation_key = str(conversation_id)
        async with self._repositories_provider() as repositories:
            conversation = await repositories.conversations.get_by_id(conversation_id)
        if conversation is not None and conversation.mode == "human":
            return

        await self._schedule_processing(conversation_key, message_id, text, None)

    async def _schedule_processing(
        self,
        conversation_key: str,
        message_id: str,
        text: str,
        button_payload: str | None,
    ) -> None:
        self._pending_messages.setdefault(conversation_key, []).append(
            (message_id, text, button_payload)
        )
        token = await self._debounce_tracker.touch(conversation_key)

        # NOTE (Etapa 4 design ADR "Debounce trigger mechanism"): this
        # `asyncio.create_task` lives only in this FastAPI process's event
        # loop. A process restart, or running more than one Uvicorn worker
        # (`--workers > 1`), loses in-flight debounce timers, the pending
        # per-conversation message accumulator above, and this task-tracking
        # set — single-worker deployment is a hard requirement until Etapa
        # 7's dedicated worker process exists. Superseded runs self-detect
        # via `DebounceTracker.is_stale()` in `_debounce_and_process` rather
        # than being explicitly cancelled.
        task = asyncio.create_task(self._debounce_and_process(conversation_key, token))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _debounce_and_process(self, conversation_key: str, token: str) -> None:
        await asyncio.sleep(self._debounce_seconds)

        if await self._debounce_tracker.is_stale(conversation_key, token):
            # A newer message re-touched the window; the newer scheduled
            # run will process the (now larger) accumulated group instead.
            return

        async with redis_lock(
            self._redis_client, f"lock:conversation:{conversation_key}"
        ) as acquired:
            if not acquired:
                # Drop-on-failure, per the design's ADR: the message(s)
                # already persisted in `execute()` remain in storage
                # untouched — only handoff to the Etapa 5 seam is skipped
                # for THIS run. Either another in-flight run already holds
                # the lock and will process this conversation's group, or
                # the next inbound message re-touches the debounce window
                # and schedules a fresh attempt. No retry/requeue happens.
                logger.warning(
                    "ingest_message.lock_not_acquired conversation=%s", conversation_key
                )
                return

            async with self._repositories_provider() as repositories:
                conversation = await repositories.conversations.get_by_id(
                    ConversationId(conversation_key)
                )
            if conversation is not None and conversation.mode == "human":
                # Mode may have flipped to human while the debounce window
                # was waiting — do not forward to the agent.
                return

            grouped = self._pending_messages.pop(conversation_key, [])
            if not grouped:
                return
            message_ids = [message_id for message_id, _, _ in grouped]
            user_message = "\n".join(text for _, text, _ in grouped)
            # Last non-null button payload wins — a deliberate button tap is
            # a terminal action that should take priority over any free
            # text debounced alongside it (PRD.md §6: buttons carry a KNOWN
            # intent and must not be reinterpreted).
            button_payload = next(
                (payload for _, _, payload in reversed(grouped) if payload is not None), None
            )

            await self._agent_invoker.handle(
                ConversationId(conversation_key), message_ids, user_message, button_payload
            )

    async def _resolve_or_create_contact(
        self, contact_repository: ContactRepository, phone: PhoneNumber
    ) -> Contact:
        contact = await contact_repository.get_by_phone(phone)
        if contact is not None:
            return contact
        contact = Contact(id=str(uuid4()), phone=phone, patient_id=None)
        await contact_repository.save(contact)
        return contact

    async def _resolve_or_create_conversation(
        self,
        conversation_repository: ConversationRepository,
        from_phone: PhoneNumber,
        contact_id: str,
    ) -> Conversation:
        # YCloud/WhatsApp conversations are 1:1 with the sender's phone
        # number (no separate vendor conversation-id concept, unlike
        # Chatwoot's ticket-style `conversation.id`) — so our ConversationId
        # IS `ycloud-{phone}`, a deliberate zero-migration id-encoding
        # convention, not a hack.
        conversation_id = ConversationId(f"ycloud-{from_phone}")
        conversation = await conversation_repository.get_by_id(conversation_id)
        if conversation is not None:
            return conversation
        conversation = Conversation(
            id=conversation_id,
            contact_id=contact_id,
            mode="agent",
            created_at=datetime.now(UTC),
        )
        await conversation_repository.save(conversation)
        return conversation
