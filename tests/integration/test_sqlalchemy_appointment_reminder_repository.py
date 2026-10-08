"""Reminder rows carry Dentalink EXTERNAL ids: no local appointments/patients rows exist.

These tests deliberately never insert an `AppointmentModel` or `PatientModel`; they
run only with `INTEGRATION_DB_TESTS_ENABLED=true` against a disposable Postgres
(see `conftest.db_session`).
"""

from datetime import UTC, datetime, timedelta

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.repositories.appointment_reminder_repository import (
    SqlAlchemyAppointmentReminderRepository,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
PHONE = PhoneNumber("+5491100000001")


def _reminder(
    reminder_id: str = "rem-1",
    *,
    appointment_id: str = "9001",
    patient_id: str = "7001",
    kind: str = "confirm_day_before",
    due_at: datetime = NOW - timedelta(minutes=1),
    starts_at: datetime | None = NOW + timedelta(hours=26),
) -> AppointmentReminder:
    return AppointmentReminder(
        id=reminder_id,
        appointment_id=appointment_id,
        patient_id=patient_id,
        kind=kind,  # type: ignore[arg-type]
        status="pending",
        due_at=due_at,
        recipient_phone=str(PHONE),
        appointment_starts_at=starts_at,
    )


async def test_upsert_persists_a_reminder_with_dentalink_ids_and_no_local_rows(db_session):
    repository = SqlAlchemyAppointmentReminderRepository(db_session)

    assert await repository.upsert(_reminder()) is True

    due = await repository.list_due(NOW, limit=10)
    assert [(r.id, r.appointment_id, r.patient_id) for r in due] == [("rem-1", "9001", "7001")]


async def test_claim_then_mark_sent_transitions_the_row(db_session):
    repository = SqlAlchemyAppointmentReminderRepository(db_session)
    await repository.upsert(_reminder())

    assert await repository.claim("rem-1", NOW) is True
    assert await repository.list_due(NOW, limit=10) == []
    assert (
        await repository.mark_sent(
            "rem-1", claimed_at=NOW, external_message_id="wamid.1", sent_at=NOW
        )
        is True
    )

    sent = await repository.find_sent_for_inbound_action("9001", PHONE, ("confirm_day_before",))
    assert sent is not None
    assert sent.status == "sent"
    assert sent.external_message_id == "wamid.1"


async def test_latest_sent_pending_reminder_and_appointment_start_for_the_phone(db_session):
    repository = SqlAlchemyAppointmentReminderRepository(db_session)
    earlier = _reminder("rem-a", appointment_id="9001", starts_at=NOW + timedelta(hours=5))
    later = _reminder("rem-b", appointment_id="9002", starts_at=NOW + timedelta(hours=30))
    past = _reminder("rem-c", appointment_id="9003", starts_at=NOW - timedelta(hours=1))
    for index, reminder in enumerate((earlier, later, past)):
        await repository.upsert(reminder)
        await repository.claim(reminder.id, NOW)
        await repository.mark_sent(
            reminder.id,
            claimed_at=NOW,
            external_message_id=f"wamid.{index}",
            sent_at=NOW + timedelta(minutes=index),
        )

    latest = await repository.find_latest_sent_pending_appointment_reminder(
        PHONE, sent_since=NOW - timedelta(hours=48), now=NOW
    )
    assert latest is not None
    # `past` was sent last but its appointment already started, so `later` wins.
    assert latest.id == "rem-b"
    assert await repository.latest_pending_appointment_start(PHONE, now=NOW) == (
        NOW + timedelta(hours=30)
    )


async def test_review_request_dedup_queries_use_the_external_patient_id(db_session):
    repository = SqlAlchemyAppointmentReminderRepository(db_session)
    await repository.upsert(_reminder("rem-r", kind="review_request", starts_at=None))
    await repository.claim("rem-r", NOW)
    await repository.mark_sent("rem-r", claimed_at=NOW, external_message_id="wamid.r", sent_at=NOW)

    assert await repository.has_sent_review_request_since("7001", NOW - timedelta(days=1))
    assert await repository.has_sent_review_request_for_recipient(PHONE)
