from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.agent.graph import build_state_reset_graph
from app.application.appointments.schedule_follow_up import (
    APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
    APPOINTMENT_FLOW_FOLLOW_UP_RESET,
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
    {APPOINTMENT_FLOW_FOLLOW_UP_PROMPT, APPOINTMENT_FLOW_FOLLOW_UP_RESET}
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
    of this module's own two `action_type`s and processes each.

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
            await send_reply.execute(contact.phone, _FOLLOW_UP_PROMPT_MESSAGE)
            await _record_outbound(
                message_repository, conversation_id, _FOLLOW_UP_PROMPT_MESSAGE, now
            )
            await _schedule_reset(
                scheduled_action_repository, conversation_id, now, reset_delay_seconds
            )
        else:
            reset_graph = build_state_reset_graph(checkpointer)
            await reset_graph.aupdate_state(
                {"configurable": {"thread_id": str(conversation_id)}}, {"collected_data": {}}
            )
            await send_reply.execute(contact.phone, _FOLLOW_UP_RESET_MESSAGE)
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
