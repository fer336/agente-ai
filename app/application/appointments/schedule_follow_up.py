from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey

#: Fires first: the agent was the last to speak and the patient's trámite
#: is still open — asks whether they want to continue (this session's own
#: brief, no PRD.md section). `pending_action_id=None` always, since this
#: can fire well before any `PendingAction` exists (e.g. still typing
#: their DNI).
APPOINTMENT_FLOW_FOLLOW_UP_PROMPT = "appointment_flow_follow_up_prompt"
#: Fires a further delay after the prompt above, if STILL no reply —
#: resets the stuck trámite. Always WITH a message (this session's own
#: brief: "no reiniciar en silencio").
APPOINTMENT_FLOW_FOLLOW_UP_RESET = "appointment_flow_follow_up_reset"

#: The two `action_type`s this use case owns — never touches an unrelated
#: `ScheduledAction` (e.g. `appointment_confirmation_timeout`, owned by
#: `ProposeAppointmentUseCase`) even when it shares the same conversation.
_FOLLOW_UP_ACTION_TYPES = frozenset(
    {APPOINTMENT_FLOW_FOLLOW_UP_PROMPT, APPOINTMENT_FLOW_FOLLOW_UP_RESET}
)


class ScheduleFollowUpUseCase:
    """Reconciles one conversation's inactivity follow-up at the end of
    every turn (this session's own brief — PRD.md has no section for
    this).

    Reuses the SAME `ScheduledAction` machinery
    `ProposeAppointmentUseCase`'s confirmation timeout already relies on
    (`get_due`/`transition_status`'s atomic race guard) — the follow-up
    worker (`app.workers.follow_up_worker`) is what actually consumes what
    this schedules.
    """

    def __init__(
        self,
        scheduled_action_repository: ScheduledActionRepository,
        prompt_delay_seconds: int,
    ) -> None:
        self._scheduled_action_repository = scheduled_action_repository
        self._prompt_delay_seconds = prompt_delay_seconds

    async def reconcile(self, conversation_id: ConversationId, stage: object) -> None:
        """`stage` is `collected_data.get("stage")` at the end of a turn.

        `None` (the trámite ended or never started) cancels any follow-up
        a PRIOR turn left scheduled — the patient just spoke, so it's
        stale either way. Anything else replaces whatever was scheduled
        before with a fresh one: the 20-minute window always counts from
        the agent's MOST RECENT reply, never an earlier turn's.
        """
        existing = await self._scheduled_action_repository.get_scheduled_by_conversation_id(
            str(conversation_id)
        )
        for scheduled_action in existing:
            if scheduled_action.action_type in _FOLLOW_UP_ACTION_TYPES:
                await self._scheduled_action_repository.transition_status(
                    scheduled_action.id, from_status="scheduled", to_status="cancelled"
                )

        if stage is None:
            return

        new_id = str(uuid4())
        await self._scheduled_action_repository.save(
            ScheduledAction(
                id=new_id,
                conversation_id=conversation_id,
                pending_action_id=None,
                action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
                status="scheduled",
                scheduled_for=datetime.now(UTC) + timedelta(seconds=self._prompt_delay_seconds),
                idempotency_key=IdempotencyKey(value=f"follow_up_prompt:{new_id}"),
                attempts=0,
            )
        )
