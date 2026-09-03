import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from redis.asyncio import Redis

from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.application.messages.send_reply import SendReplyUseCase
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
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
)
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.redis.debounce import DebounceTracker
from app.infrastructure.redis.lock import redis_lock

logger = logging.getLogger(__name__)

#: Redis key prefix for the per-conversation-per-minute audio counter
#: (PRD.md §24.3/§68 `AUDIO_RATE_LIMIT_PER_CONVERSATION_PER_MINUTE`).
_AUDIO_RATE_LIMIT_KEY_PREFIX = "audio_rate_limit:conversation:"
_AUDIO_RATE_LIMIT_WINDOW_SECONDS = 60

#: PRD.md §7's welcome message — sent exactly once, on a conversation's
#: very first inbound message (see `_resolve_or_create_conversation`'s
#: "just created" branch, the only place that can know this). No clinic
#: name is configured anywhere in `Settings` (see that module), so this
#: stays deliberately generic rather than inventing a brand.
_WELCOME_TEXT = (
    "¡Hola! 👋 Soy el asistente virtual de tu clínica dental.\n"
    "Puedo ayudarte a sacar un turno, contarte qué especialidades atendemos "
    "o comunicarte con administración. Elegí una opción para arrancar:"
)
_WELCOME_BUTTONS = [
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Turnos"),
    InteractiveButton(id=MENU_SPECIALTIES_PAYLOAD, title="Especialidades"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="Administración"),
]


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
        send_reply: SendReplyUseCase,
        audio_rate_limit_per_minute: int = 0,
    ) -> None:
        self._repositories_provider = repositories_provider
        self._debounce_tracker = debounce_tracker
        self._redis_client = redis_client
        self._agent_invoker = agent_invoker
        self._debounce_seconds = debounce_seconds
        #: Etapa 5's own `AgentInvoker`/`SendReplyUseCase` pair already
        #: sends the graph's reply after Etapa 4 hands off — this is a
        #: SEPARATE use of the same use case, for the one reply Etapa 4
        #: itself is responsible for (the welcome message), which exists
        #: before there is any graph turn to reply to.
        self._send_reply = send_reply
        #: PRD.md §24.3's per-conversation audio rate limit. `0` (the
        #: default) disables the check entirely — every existing caller
        #: that builds this use case without the new parameter (tests,
        #: pre-audio DI wiring) keeps its previous, unlimited behavior.
        self._audio_rate_limit_per_minute = audio_rate_limit_per_minute
        # Per-conversation accumulator of (message_id, text, button_payload,
        # wamid) tuples awaiting grouping into one Etapa-5 handoff. In-process
        # only — see the class docstring's singleton-lifetime note and the
        # design's "Debounce trigger mechanism" ADR (no ARQ/durable queue
        # this etapa).
        self._pending_messages: dict[str, list[tuple[str, str, str | None, str | None]]] = {}
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
            conversation, is_new_conversation = await self._resolve_or_create_conversation(
                repositories.conversations, dto.from_phone, contact.id
            )
            conversation_key = str(conversation.id)

            if is_new_conversation:
                # Sent synchronously, inline in this same request — NOT
                # fire-and-forget — so a delivery failure surfaces as this
                # request's own error (and gets retried by the caller's
                # webhook-retry semantics) instead of being silently
                # swallowed in an unawaited background task. This only
                # runs once per conversation ever (gated on the "just
                # created" branch below), so the extra latency it adds is
                # a one-time cost, not a per-message one. Runs BEFORE the
                # audio-vs-text branch below so a brand-new conversation's
                # first message gets the welcome menu even if that first
                # message is itself an audio note.
                await self._send_reply.execute(dto.from_phone, _WELCOME_TEXT, _WELCOME_BUTTONS)

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
            conversation_key,
            message.id,
            message.text,
            dto.button_payload,
            str(external_message_id),
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

        # No wamid to thread through here — a transcript has no inbound
        # webhook payload of its own, and the typing indicator is a
        # best-effort nicety (skipped, not worth a repository round-trip
        # to look one up for the audio-resume path specifically).
        await self._schedule_processing(conversation_key, message_id, text, None, None)

    async def _schedule_processing(
        self,
        conversation_key: str,
        message_id: str,
        text: str,
        button_payload: str | None,
        wamid: str | None,
    ) -> None:
        self._pending_messages.setdefault(conversation_key, []).append(
            (message_id, text, button_payload, wamid)
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
            message_ids = [message_id for message_id, _, _, _ in grouped]
            user_message = "\n".join(text for _, text, _, _ in grouped)
            # Last non-null button payload wins — a deliberate button tap is
            # a terminal action that should take priority over any free
            # text debounced alongside it (PRD.md §6: buttons carry a KNOWN
            # intent and must not be reinterpreted).
            button_payload = next(
                (payload for _, _, payload, _ in reversed(grouped) if payload is not None), None
            )
            latest_wamid = next(
                (wamid for _, _, _, wamid in reversed(grouped) if wamid is not None), None
            )

            if latest_wamid is not None:
                # Best-effort only: per YCloud's own guidance, only show
                # "typing..." when we're actually about to reply, which is
                # always true here — but a failure of this purely cosmetic
                # call must never block the real reply that follows.
                try:
                    await self._send_reply.send_typing_indicator(latest_wamid)
                except Exception:
                    logger.warning(
                        "ingest_message.typing_indicator_failed conversation=%s",
                        conversation_key,
                        exc_info=True,
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
    ) -> tuple[Conversation, bool]:
        # YCloud/WhatsApp conversations are 1:1 with the sender's phone
        # number (no separate vendor conversation-id concept, unlike
        # Chatwoot's ticket-style `conversation.id`) — so our ConversationId
        # IS `ycloud-{phone}`, a deliberate zero-migration id-encoding
        # convention, not a hack.
        conversation_id = ConversationId(f"ycloud-{from_phone}")
        conversation = await conversation_repository.get_by_id(conversation_id)
        if conversation is not None:
            return conversation, False
        conversation = Conversation(
            id=conversation_id,
            contact_id=contact_id,
            mode="agent",
            created_at=datetime.now(UTC),
        )
        await conversation_repository.save(conversation)
        # The `bool` here is the ONLY place in this class that can tell a
        # conversation's first-ever turn apart from any later one — by the
        # time any other method runs, the row this same call just saved is
        # already indistinguishable from an old one. `execute()` uses it to
        # fire the once-ever welcome message (PRD.md §7).
        return conversation, True
