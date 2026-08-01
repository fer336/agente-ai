from datetime import UTC, datetime, timedelta

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.repositories.pending_action_repository import (
    SqlAlchemyPendingActionRepository,
)


def _pending_action(conversation_id: str, action_id: str, status: str) -> PendingAction:
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    return PendingAction(
        id=action_id,
        conversation_id=ConversationId(value=conversation_id),
        action_type="create_appointment",
        payload={"slot_id": "slot-1"},
        confirmation_token=ConfirmationToken(value=f"token-{action_id}"),
        status=status,
        expires_at=now + timedelta(minutes=10),
    )


async def test_save_then_get_by_id_round_trips_a_pending_action(db_session, conversation_id):
    repository = SqlAlchemyPendingActionRepository(db_session)
    pending_action = _pending_action(conversation_id, "pa-1", "pending")

    await repository.save(pending_action)
    fetched = await repository.get_by_id("pa-1")

    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.payload == {"slot_id": "slot-1"}


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyPendingActionRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_get_pending_for_conversation_excludes_non_pending_actions(
    db_session, conversation_id
):
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-2", "pending"))
    await repository.save(_pending_action(conversation_id, "pa-3", "confirmed"))

    pending = await repository.get_pending_for_conversation(ConversationId(value=conversation_id))

    assert {action.id for action in pending} == {"pa-2"}
