from app.domain.entities.outbox_event import OutboxEvent
from app.infrastructure.database.repositories.outbox_repository import SqlAlchemyOutboxRepository


async def test_save_then_fetch_pending_returns_the_event(db_session):
    repository = SqlAlchemyOutboxRepository(db_session)
    event = OutboxEvent(
        id="evt-1",
        event_type="appointment.created",
        aggregate_type="appointment",
        aggregate_id="appt-1",
        payload={"appointment_id": "appt-1"},
        status="pending",
        attempts=0,
    )

    await repository.save(event)
    pending = await repository.fetch_pending(limit=10)

    assert [item.id for item in pending] == ["evt-1"]


async def test_mark_processed_excludes_the_event_from_fetch_pending(db_session):
    repository = SqlAlchemyOutboxRepository(db_session)
    event = OutboxEvent(
        id="evt-2",
        event_type="reminder.requested",
        aggregate_type="appointment",
        aggregate_id="appt-2",
        payload={},
        status="pending",
        attempts=0,
    )
    await repository.save(event)

    await repository.mark_processed("evt-2")
    pending = await repository.fetch_pending(limit=10)

    assert pending == []
