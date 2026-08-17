from datetime import UTC, datetime

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_pending_action_with_all_fields():
    pending_action = PendingAction(
        id="pa-1",
        conversation_id=ConversationId(value="conv-1"),
        action_type="create_appointment",
        payload={"slot_id": "slot-1"},
        confirmation_token=ConfirmationToken(value="token-1"),
        status="pending",
        expires_at=datetime(2026, 8, 4, 9, 10, tzinfo=UTC),
    )

    assert pending_action.action_type == "create_appointment"
    assert pending_action.payload == {"slot_id": "slot-1"}
    assert pending_action.status == "pending"


def test_pending_actions_with_different_status_are_not_equal():
    expires_at = datetime(2026, 8, 4, 9, 10, tzinfo=UTC)
    first = PendingAction(
        id="pa-2",
        conversation_id=ConversationId(value="conv-2"),
        action_type="cancel_appointment",
        payload={},
        confirmation_token=ConfirmationToken(value="token-2"),
        status="pending",
        expires_at=expires_at,
    )
    second = PendingAction(
        id="pa-2",
        conversation_id=ConversationId(value="conv-2"),
        action_type="cancel_appointment",
        payload={},
        confirmation_token=ConfirmationToken(value="token-2"),
        status="confirmed",
        expires_at=expires_at,
    )

    assert first != second
