from datetime import UTC, datetime

from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey


def test_creates_scheduled_action_with_all_fields():
    scheduled_action = ScheduledAction(
        id="sa-1",
        conversation_id=ConversationId(value="conv-1"),
        pending_action_id="pa-1",
        action_type="appointment_confirmation_timeout",
        status="scheduled",
        scheduled_for=datetime(2026, 8, 4, 9, 12, tzinfo=UTC),
        idempotency_key=IdempotencyKey(value="idem-1"),
        attempts=0,
    )

    assert scheduled_action.action_type == "appointment_confirmation_timeout"
    assert scheduled_action.status == "scheduled"
    assert scheduled_action.pending_action_id == "pa-1"
    assert scheduled_action.attempts == 0


def test_scheduled_actions_with_different_status_are_not_equal():
    scheduled_for = datetime(2026, 8, 4, 9, 12, tzinfo=UTC)
    first = ScheduledAction(
        id="sa-2",
        conversation_id=ConversationId(value="conv-2"),
        pending_action_id="pa-2",
        action_type="appointment_confirmation_timeout",
        status="scheduled",
        scheduled_for=scheduled_for,
        idempotency_key=IdempotencyKey(value="idem-2"),
        attempts=0,
    )
    second = ScheduledAction(
        id="sa-2",
        conversation_id=ConversationId(value="conv-2"),
        pending_action_id="pa-2",
        action_type="appointment_confirmation_timeout",
        status="completed",
        scheduled_for=scheduled_for,
        idempotency_key=IdempotencyKey(value="idem-2"),
        attempts=1,
    )

    assert first != second
