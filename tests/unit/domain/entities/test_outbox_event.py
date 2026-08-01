from app.domain.entities.outbox_event import OutboxEvent


def test_creates_outbox_event_with_all_fields():
    event = OutboxEvent(
        id="evt-1",
        event_type="appointment.created",
        aggregate_type="appointment",
        aggregate_id="appt-1",
        payload={"appointment_id": "appt-1"},
        status="pending",
        attempts=0,
    )

    assert event.event_type == "appointment.created"
    assert event.status == "pending"
    assert event.attempts == 0


def test_outbox_events_with_different_attempts_are_not_equal():
    first = OutboxEvent(
        id="evt-2",
        event_type="reminder.requested",
        aggregate_type="appointment",
        aggregate_id="appt-2",
        payload={},
        status="pending",
        attempts=0,
    )
    second = OutboxEvent(
        id="evt-2",
        event_type="reminder.requested",
        aggregate_type="appointment",
        aggregate_id="appt-2",
        payload={},
        status="pending",
        attempts=1,
    )

    assert first != second
