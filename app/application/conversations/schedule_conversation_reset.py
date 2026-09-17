from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey

#: Fires when a conversation has been completely silent (no inbound message
#: in either direction) for `delay_seconds` — unlike
#: `app.application.appointments.schedule_follow_up`'s follow-up/reset pair,
#: this applies regardless of whether a booking trámite is in progress, and
#: is reconciled on EVERY inbound message, not just ones that leave an
#: active `stage`. `app.workers.follow_up_worker` is what actually consumes
#: what this schedules.
CONVERSATION_IDLE_RESET_ACTION = "conversation_idle_reset"


class ScheduleConversationResetUseCase:
    """Reconciles one conversation's idle-reset timer at the end of every
    inbound message (this session's own brief, no PRD.md section): the
    patient asked for the bot to "start over from zero" with the welcome
    menu after a couple of hours of silence, and nothing currently does
    that for a conversation in normal `mode="agent"` operation — only a
    `mode="human"` handoff's own lazy-timeout reactivation
    (`IngestMessageUseCase._HUMAN_MODE_REACTIVATION_TIMEOUT`) sends a
    welcome menu on a timer, and only when reactivating from a human
    handoff.

    Reuses the same `ScheduledAction` machinery `ScheduleFollowUpUseCase`
    already relies on (`get_due`/`transition_status`'s atomic race guard).
    """

    def __init__(
        self,
        scheduled_action_repository: ScheduledActionRepository,
        delay_seconds: int,
    ) -> None:
        self._scheduled_action_repository = scheduled_action_repository
        self._delay_seconds = delay_seconds

    async def reconcile(self, conversation_id: ConversationId) -> None:
        """Cancels whatever idle-reset was scheduled before (the patient
        just spoke, so it's stale either way) and schedules a fresh one —
        the window always counts from the MOST RECENT inbound message,
        never an earlier one."""
        existing = await self._scheduled_action_repository.get_scheduled_by_conversation_id(
            str(conversation_id)
        )
        for scheduled_action in existing:
            if scheduled_action.action_type == CONVERSATION_IDLE_RESET_ACTION:
                await self._scheduled_action_repository.transition_status(
                    scheduled_action.id, from_status="scheduled", to_status="cancelled"
                )

        new_id = str(uuid4())
        await self._scheduled_action_repository.save(
            ScheduledAction(
                id=new_id,
                conversation_id=conversation_id,
                pending_action_id=None,
                action_type=CONVERSATION_IDLE_RESET_ACTION,
                status="scheduled",
                scheduled_for=datetime.now(UTC) + timedelta(seconds=self._delay_seconds),
                idempotency_key=IdempotencyKey(value=f"conversation_idle_reset:{new_id}"),
                attempts=0,
            )
        )
