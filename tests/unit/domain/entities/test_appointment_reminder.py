from datetime import UTC, datetime

from app.domain.entities.appointment_reminder import AppointmentReminder


def test_reminder_keeps_retry_delivery_data_without_exposing_recipient_in_repr():
    reminder = AppointmentReminder(
        id="reminder-1",
        appointment_id="appointment-1",
        patient_id="patient-1",
        kind="confirm_day_before",
        status="pending",
        due_at=datetime(2026, 10, 1, 21, tzinfo=UTC),
        recipient_phone="+5491112345678",
    )

    assert reminder.attempts == 0
    assert reminder.claimed_at is None
    assert "+5491112345678" not in repr(reminder)
