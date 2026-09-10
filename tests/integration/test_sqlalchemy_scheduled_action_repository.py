from datetime import UTC, datetime, timedelta

from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey
from app.infrastructure.database.models.contact import ContactModel
from app.infrastructure.database.models.conversation import ConversationModel
from app.infrastructure.database.repositories.scheduled_action_repository import (
    SqlAlchemyScheduledActionRepository,
)


def _scheduled_action(
    conversation_id: str,
    pending_action_id: str,
    action_id: str,
    status: str,
    scheduled_for: datetime,
) -> ScheduledAction:
    return ScheduledAction(
        id=action_id,
        conversation_id=ConversationId(value=conversation_id),
        pending_action_id=pending_action_id,
        action_type="appointment_confirmation_timeout",
        status=status,
        scheduled_for=scheduled_for,
        idempotency_key=IdempotencyKey(value=f"idem-{action_id}"),
        attempts=0,
    )


async def test_save_then_get_by_id_round_trips_a_scheduled_action(
    db_session, conversation_id, pending_action_id
):
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    scheduled_action = _scheduled_action(
        conversation_id, pending_action_id, "sa-1", "scheduled", now + timedelta(seconds=120)
    )

    await repository.save(scheduled_action)
    fetched = await repository.get_by_id("sa-1")

    assert fetched is not None
    assert fetched.status == "scheduled"
    assert fetched.pending_action_id == pending_action_id
    assert fetched.idempotency_key == IdempotencyKey(value="idem-sa-1")


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyScheduledActionRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_get_due_returns_only_scheduled_actions_due_by_now(
    db_session, conversation_id, pending_action_id
):
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await repository.save(
        _scheduled_action(
            conversation_id, pending_action_id, "sa-due", "scheduled", now - timedelta(seconds=5)
        )
    )
    await repository.save(
        _scheduled_action(
            conversation_id,
            pending_action_id,
            "sa-not-due",
            "scheduled",
            now + timedelta(seconds=60),
        )
    )
    await repository.save(
        _scheduled_action(
            conversation_id,
            pending_action_id,
            "sa-already-completed",
            "completed",
            now - timedelta(seconds=5),
        )
    )

    due = await repository.get_due(now, limit=10)

    assert [action.id for action in due] == ["sa-due"]


async def test_get_by_pending_action_id_returns_the_matching_scheduled_action(
    db_session, conversation_id, pending_action_id
):
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await repository.save(
        _scheduled_action(conversation_id, pending_action_id, "sa-lookup", "scheduled", now)
    )

    fetched = await repository.get_by_pending_action_id(pending_action_id)

    assert fetched is not None
    assert fetched.id == "sa-lookup"


async def test_get_by_pending_action_id_returns_none_when_no_match(db_session):
    repository = SqlAlchemyScheduledActionRepository(db_session)

    assert await repository.get_by_pending_action_id("missing") is None


async def test_transition_status_succeeds_when_status_matches_from_status(
    db_session, conversation_id, pending_action_id
):
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await repository.save(
        _scheduled_action(conversation_id, pending_action_id, "sa-2", "scheduled", now)
    )

    won = await repository.transition_status(
        "sa-2", from_status="scheduled", to_status="processing"
    )

    assert won is True
    fetched = await repository.get_by_id("sa-2")
    assert fetched is not None
    assert fetched.status == "processing"


async def test_transition_status_fails_when_status_no_longer_matches_from_status(
    db_session, conversation_id, pending_action_id
):
    # Simulates the race PRD.md §16.3/§75.9 guards against: two workers
    # both trying to claim the same due scheduled action.
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await repository.save(
        _scheduled_action(conversation_id, pending_action_id, "sa-3", "scheduled", now)
    )
    first_worker_won = await repository.transition_status(
        "sa-3", from_status="scheduled", to_status="processing"
    )

    second_worker_won = await repository.transition_status(
        "sa-3", from_status="scheduled", to_status="processing"
    )

    assert first_worker_won is True
    assert second_worker_won is False
    fetched = await repository.get_by_id("sa-3")
    assert fetched is not None
    assert fetched.status == "processing"


async def test_save_accepts_a_scheduled_action_with_no_pending_action_yet(
    db_session, conversation_id
):
    # An inactivity follow-up for a patient stuck mid-flow (still typing
    # their DNI, say) has no `PendingAction` to attach to — this is the
    # migration 0011 change (`pending_action_id` now nullable) exercised
    # for real against Postgres.
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    scheduled_action = ScheduledAction(
        id="sa-no-pending",
        conversation_id=ConversationId(value=conversation_id),
        pending_action_id=None,
        action_type="appointment_flow_follow_up_prompt",
        status="scheduled",
        scheduled_for=now,
        idempotency_key=IdempotencyKey(value="idem-sa-no-pending"),
        attempts=0,
    )

    await repository.save(scheduled_action)
    fetched = await repository.get_by_id("sa-no-pending")

    assert fetched is not None
    assert fetched.pending_action_id is None


async def test_get_scheduled_by_conversation_id_returns_only_this_conversations_scheduled_rows(
    db_session, conversation_id, pending_action_id
):
    repository = SqlAlchemyScheduledActionRepository(db_session)
    now = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    await repository.save(
        _scheduled_action(conversation_id, pending_action_id, "sa-scheduled", "scheduled", now)
    )
    await repository.save(
        _scheduled_action(conversation_id, pending_action_id, "sa-cancelled", "cancelled", now)
    )
    other_contact = ContactModel(id="contact-other", phone="+5491100000001")
    db_session.add(other_contact)
    await db_session.flush()
    other_conversation = ConversationModel(
        id="conv-other", contact_id="contact-other", mode="agent"
    )
    db_session.add(other_conversation)
    await db_session.flush()
    await repository.save(
        _scheduled_action("conv-other", pending_action_id, "sa-other-conv", "scheduled", now)
    )

    found = await repository.get_scheduled_by_conversation_id(conversation_id)

    assert [action.id for action in found] == ["sa-scheduled"]
