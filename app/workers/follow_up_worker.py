import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.application.appointments.schedule_follow_up import (
    APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
    APPOINTMENT_FLOW_FOLLOW_UP_RESET,
)
from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
)
from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    SetConversationInputStateUseCase,
)
from app.application.messages.send_reply import SendReplyUseCase
from app.domain.entities.message import ROLE_ASSISTANT, Message
from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.idempotency_key import IdempotencyKey

logger = logging.getLogger(__name__)

#: This session's own brief: reworded, cordial follow-up copy — never
#: apologetic (same tone rule `appointment.py`'s identification retry
#: already follows), and the reset message is explicit per the user's own
#: decision: "no reiniciar en silencio".
_FOLLOW_UP_PROMPT_MESSAGE = (
    "¿Seguís ahí? Si querés continuar con tu trámite, escribime cuando quieras — acá te espero."
)
_FOLLOW_UP_RESET_MESSAGE = (
    "Como no tuve respuesta, reinicié el trámite. Si querés arrancar de nuevo, "
    "contame qué necesitás."
)

_OWNED_ACTION_TYPES = frozenset(
    {
        APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
        APPOINTMENT_FLOW_FOLLOW_UP_RESET,
        CONVERSATION_IDLE_RESET_ACTION,
    }
)


async def run_follow_up_tick(
    scheduled_action_repository: ScheduledActionRepository,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    send_reply: SendReplyUseCase,
    checkpointer: "Any",
    *,
    now: datetime,
    limit: int,
    reset_delay_seconds: int,
) -> int:
    """Inactivity follow-up sweep — one poll tick (this session's own
    brief, no PRD.md section): claims up to `limit` due `ScheduledAction`s
    of this module's own `action_type`s (the appointment-flow follow-up
    prompt/reset pair, and the conversation-level idle reset) and
    processes each.

    DELIBERATELY NOT a running process/scheduler on its own — mirrors the
    exact convention `app.workers.audio_tasks`/`incident_tasks`/
    `memory_tasks` already use. `app.main`'s `lifespan` is what turns this
    into an actual periodic loop.

    Never claims a `ScheduledAction` this module doesn't own (e.g.
    `appointment_confirmation_timeout`, owned by `ProposeAppointmentUseCase`)
    — those are filtered out BEFORE any `transition_status` call, so they
    are left exactly as `get_due` found them for whatever eventually
    consumes them.

    A row another tick/process already claimed (`transition_status`
    returns `False`) is silently skipped — PRD.md §16.3/§75.9's "Dos
    workers -> una sola ejecución" guarantee, already proven at the
    repository layer; this only has to respect it.

    Returns how many of ITS OWN due rows were attempted (sent, or
    correctly determined stale and cancelled) — not a count of messages
    sent, since a stale row that gets cancelled without sending still
    counts as "handled this tick."
    """
    due = await scheduled_action_repository.get_due(now, limit)
    processed = 0

    for scheduled_action in due:
        if scheduled_action.action_type not in _OWNED_ACTION_TYPES:
            continue

        won = await scheduled_action_repository.transition_status(
            scheduled_action.id, from_status="scheduled", to_status="processing"
        )
        if not won:
            continue

        processed += 1
        conversation_id = scheduled_action.conversation_id

        if scheduled_action.action_type == CONVERSATION_IDLE_RESET_ACTION:
            # Unlike the appointment-flow pair below, this action's own
            # staleness check IS the CAS win above: `reconcile()` cancels
            # and reschedules this row on EVERY inbound message, so a row
            # still `scheduled` by the time it's claimed here means
            # nothing happened in EITHER direction since it was set —
            # `_agent_is_last_to_speak` would wrongly skip a conversation
            # whose last message was the patient's own (e.g. a closing
            # "Gracias" the agent already answered).
            await _handle_conversation_idle_reset(conversation_repository, conversation_id)
            await scheduled_action_repository.transition_status(
                scheduled_action.id, from_status="processing", to_status="executed"
            )
            continue

        agent_still_last_to_speak = await _agent_is_last_to_speak(
            message_repository, conversation_id
        )
        if not agent_still_last_to_speak:
            # The patient replied since this was scheduled — the
            # condition that justified this follow-up no longer holds.
            await scheduled_action_repository.transition_status(
                scheduled_action.id, from_status="processing", to_status="cancelled"
            )
            continue

        contact = await _resolve_contact(
            conversation_repository, contact_repository, conversation_id
        )
        if contact is None:
            await scheduled_action_repository.transition_status(
                scheduled_action.id, from_status="processing", to_status="cancelled"
            )
            continue

        if scheduled_action.action_type == APPOINTMENT_FLOW_FOLLOW_UP_PROMPT:
            await send_reply.execute(conversation_id, contact.phone, _FOLLOW_UP_PROMPT_MESSAGE)
            await _record_outbound(
                message_repository, conversation_id, _FOLLOW_UP_PROMPT_MESSAGE, now
            )
            await _schedule_reset(
                scheduled_action_repository, conversation_id, now, reset_delay_seconds
            )
        else:
            # CAS-rotate the workflow generation instead of touching the
            # checkpoint directly: a bare `str(conversation_id)` thread_id
            # (the previous approach here) never matches any real
            # checkpoint row — every actual thread_id carries a
            # `:session:{generation}` suffix
            # (`app.infrastructure.agent.langgraph_agent_invoker.handle`)
            # — so this reset used to be a silent no-op even though the
            # "reinicié el trámite" message went out regardless. Rotating
            # the generation instead makes the NEXT turn start a genuinely
            # fresh, empty thread, no checkpoint access needed.
            conversation = await conversation_repository.get_by_id(conversation_id)
            if conversation is not None:
                await RotateWorkflowSessionUseCase(conversation_repository).execute(
                    conversation_id, expected_generation=conversation.workflow_session_generation
                )
            await send_reply.execute(conversation_id, contact.phone, _FOLLOW_UP_RESET_MESSAGE)
            await _record_outbound(
                message_repository, conversation_id, _FOLLOW_UP_RESET_MESSAGE, now
            )

        await scheduled_action_repository.transition_status(
            scheduled_action.id, from_status="processing", to_status="executed"
        )

    return processed


async def _agent_is_last_to_speak(
    message_repository: MessageRepository, conversation_id: ConversationId
) -> bool:
    recent = await message_repository.get_recent_by_conversation_id(conversation_id, limit=1)
    return bool(recent) and recent[-1].direction == "outbound"


async def _resolve_contact(
    conversation_repository: ConversationRepository,
    contact_repository: ContactRepository,
    conversation_id: ConversationId,
) -> Any:
    conversation = await conversation_repository.get_by_id(conversation_id)
    if conversation is None:
        return None
    return await contact_repository.get_by_id(conversation.contact_id)


async def _handle_conversation_idle_reset(
    conversation_repository: ConversationRepository,
    conversation_id: ConversationId,
) -> None:
    """The patient's own ask (revised — an earlier version of this sent the
    welcome menu proactively here, which the user explicitly asked to
    remove): after the configured idle window, a stuck workflow generation
    is retired SILENTLY, with no message of any kind. This only clears the
    hung graph server-side so the NEXT real inbound message starts a
    genuinely fresh turn instead of continuing whatever stage this one was
    left in — the patient never sees a "empezamos de cero" message unless
    they write again and normal turn routing decides to send one.

    Never fires in `mode="human"`: a staff handoff owns its own
    reactivation timing
    (`IngestMessageUseCase._HUMAN_MODE_REACTIVATION_TIMEOUT`).
    """
    conversation = await conversation_repository.get_by_id(conversation_id)
    if conversation is None or conversation.mode != "agent":
        return

    await RotateWorkflowSessionUseCase(conversation_repository).execute(
        conversation_id, expected_generation=conversation.workflow_session_generation
    )
    await SetConversationInputStateUseCase(conversation_repository).execute(
        conversation_id, FREE_INPUT
    )


async def _record_outbound(
    message_repository: MessageRepository,
    conversation_id: ConversationId,
    text: str,
    now: datetime,
) -> None:
    await message_repository.save(
        Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            external_message_id=ExternalMessageId(f"outbound-{uuid4().hex}"),
            direction="outbound",
            text=text,
            created_at=now,
            role=ROLE_ASSISTANT,
        )
    )


async def _schedule_reset(
    scheduled_action_repository: ScheduledActionRepository,
    conversation_id: ConversationId,
    now: datetime,
    reset_delay_seconds: int,
) -> None:
    new_id = str(uuid4())
    await scheduled_action_repository.save(
        ScheduledAction(
            id=new_id,
            conversation_id=conversation_id,
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_RESET,
            status="scheduled",
            scheduled_for=now + timedelta(seconds=reset_delay_seconds),
            idempotency_key=IdempotencyKey(value=f"follow_up_reset:{new_id}"),
            attempts=0,
        )
    )


@dataclass(frozen=True)
class FollowUpWorkerRepositories:
    """Bundles the repositories one `run_follow_up_loop` tick needs, all
    sharing the one short-lived session `repositories_provider` opens for
    it — same "no eager I/O, session per call" convention as every other
    process-lifetime provider in `app.api.dependencies.repositories`."""

    scheduled_actions: ScheduledActionRepository
    messages: MessageRepository
    conversations: ConversationRepository
    contacts: ContactRepository


FollowUpWorkerRepositoriesProvider = Callable[
    [], AbstractAsyncContextManager[FollowUpWorkerRepositories]
]
CheckpointerProvider = Callable[[], Awaitable[Any]]


async def run_follow_up_loop(
    repositories_provider: FollowUpWorkerRepositoriesProvider,
    checkpointer_provider: CheckpointerProvider,
    send_reply: SendReplyUseCase,
    *,
    interval_seconds: int,
    batch_limit: int,
    reset_delay_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Turns `run_follow_up_tick` into an actual running process — this
    module's own docstrings always claimed "`app.main`'s `lifespan` is what
    turns this into an actual periodic loop", but nothing ever did: neither
    `ScheduleFollowUpUseCase.reconcile()` nor this tick function had a
    caller outside their own tests, so a stuck trámite never got the
    "¿seguís ahí?" nudge or the silent-free auto-reset this whole module
    exists for. `app.main`'s `lifespan` starts this as one background task
    and cancels it on shutdown.

    One tick's failure (a transient DB error, a `send_reply` timeout the
    tick itself didn't already turn into a cancelled action) must never
    kill the whole loop — nothing else would ever restart it for the
    lifetime of the process — so it is caught and logged, not re-raised.

    `max_iterations` is test-only: `None` (the default, always used in
    production) loops forever; a finite count lets a test await this
    coroutine directly instead of racing a background task against real
    `asyncio.sleep` calls.
    """
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        try:
            checkpointer = await checkpointer_provider()
            async with repositories_provider() as repositories:
                await run_follow_up_tick(
                    repositories.scheduled_actions,
                    repositories.messages,
                    repositories.conversations,
                    repositories.contacts,
                    send_reply,
                    checkpointer,
                    now=datetime.now(UTC),
                    limit=batch_limit,
                    reset_delay_seconds=reset_delay_seconds,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("follow_up_worker.tick_failed")
        iterations += 1
        if max_iterations is None or iterations < max_iterations:
            await asyncio.sleep(interval_seconds)
