from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.pending_action import PendingActionModel
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


async def test_mark_expired_if_pending_succeeds_when_still_pending(db_session, conversation_id):
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-4", "pending"))

    expired = await repository.mark_expired_if_pending("pa-4")

    assert expired is True
    fetched = await repository.get_by_id("pa-4")
    assert fetched is not None
    assert fetched.status == "expired"


async def test_mark_expired_if_pending_fails_when_already_confirmed(db_session, conversation_id):
    # PRD.md §16.1/§16.3: a same-moment confirmation must win over a
    # follow-up expiration — the guard must not blindly overwrite status.
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-5", "confirmed"))

    expired = await repository.mark_expired_if_pending("pa-5")

    assert expired is False
    fetched = await repository.get_by_id("pa-5")
    assert fetched is not None
    assert fetched.status == "confirmed"


async def test_mark_confirmed_if_pending_succeeds_when_still_pending(db_session, conversation_id):
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-6", "pending"))

    confirmed = await repository.mark_confirmed_if_pending("pa-6")

    assert confirmed is True
    fetched = await repository.get_by_id("pa-6")
    assert fetched is not None
    assert fetched.status == "confirmed"


async def test_mark_confirmed_if_pending_fails_when_already_expired(db_session, conversation_id):
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-7", "expired"))

    confirmed = await repository.mark_confirmed_if_pending("pa-7")

    assert confirmed is False
    fetched = await repository.get_by_id("pa-7")
    assert fetched is not None
    assert fetched.status == "expired"


async def test_mark_confirmed_if_pending_stamps_confirmed_at(db_session, conversation_id):
    repository = SqlAlchemyPendingActionRepository(db_session)
    await repository.save(_pending_action(conversation_id, "pa-8", "pending"))

    await repository.mark_confirmed_if_pending("pa-8")
    rows = await repository.list_confirmed_between(
        ["create_appointment"],
        datetime.now(UTC) - timedelta(minutes=5),
        datetime.now(UTC) + timedelta(minutes=5),
        10,
    )

    assert [row.id for row in rows] == ["pa-8"]


async def test_list_confirmed_between_filters_orders_newest_first_and_applies_limit(
    db_session, conversation_id
):
    repository = SqlAlchemyPendingActionRepository(db_session)
    base = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    seeds = [
        ("k-old", "create_appointment", "confirmed", 0),
        ("k-start", "create_appointment", "confirmed", 60),
        ("k-mid", "create_appointment", "confirmed", 120),
        ("k-cancel", "cancel_appointment", "confirmed", 130),
        ("k-expired", "create_appointment", "expired", 140),
        ("k-end", "create_appointment", "confirmed", 180),
    ]
    for id_, action_type, status, minutes in seeds:
        action = _pending_action(conversation_id, id_, status)
        action.action_type = action_type
        action.payload = {"professional_id": "7"}
        await repository.save(action)
        await db_session.execute(
            update(PendingActionModel)
            .where(PendingActionModel.id == id_)
            .values(confirmed_at=base + timedelta(minutes=minutes))
        )

    start, end = base + timedelta(minutes=60), base + timedelta(minutes=180)
    rows = await repository.list_confirmed_between(["create_appointment"], start, end, 10)
    limited = await repository.list_confirmed_between(["create_appointment"], start, end, 1)

    assert [row.id for row in rows] == ["k-mid", "k-start"]
    assert [row.id for row in limited] == ["k-mid"]
    assert rows[0].conversation_id == conversation_id
    assert rows[0].payload == {"professional_id": "7"}
    assert rows[0].confirmed_at == base + timedelta(minutes=120)
