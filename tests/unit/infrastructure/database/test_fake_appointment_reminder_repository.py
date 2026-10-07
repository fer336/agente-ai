from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_appointment_reminder_repository import (
    FakeAppointmentReminderRepository,
)

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
PHONE = PhoneNumber("+5491112345678")


def row(
    reminder_id="r-1",
    *,
    kind="confirm_day_before",
    status="sent",
    sent_at=NOW - timedelta(hours=1),
    starts_at=NOW + timedelta(hours=20),
    phone=str(PHONE),
    appointment_id="apt-1",
):
    return AppointmentReminder(
        reminder_id,
        appointment_id,
        "patient-1",
        kind,
        status,
        NOW,
        phone,
        sent_at=sent_at,
        appointment_starts_at=starts_at,
    )


async def find(repository, window_hours=48):
    return await repository.find_latest_sent_pending_appointment_reminder(
        PHONE, sent_since=NOW - timedelta(hours=window_hours), now=NOW
    )


def test_the_fake_satisfies_the_port():
    assert isinstance(FakeAppointmentReminderRepository(), AppointmentReminderRepository)


@pytest.mark.asyncio
async def test_finds_a_recently_sent_reminder_for_a_future_appointment():
    repository = FakeAppointmentReminderRepository([row()])

    assert (await find(repository)).id == "r-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rejected",
    [
        row(status="pending"),
        row(kind="review_request"),
        row(phone="+5491199999999"),
        row(sent_at=NOW - timedelta(hours=49)),
        row(starts_at=NOW - timedelta(minutes=1)),
        row(starts_at=None),
        row(sent_at=None),
    ],
)
async def test_ignores_rows_outside_the_window_kind_phone_status_or_future_start(rejected):
    assert await find(FakeAppointmentReminderRepository([rejected])) is None


@pytest.mark.asyncio
async def test_returns_the_most_recently_sent_matching_reminder():
    older = row("older", sent_at=NOW - timedelta(hours=20))
    newer = row("newer", kind="confirm_or_location_same_day", sent_at=NOW - timedelta(hours=2))

    assert (await find(FakeAppointmentReminderRepository([older, newer]))).id == "newer"


@pytest.mark.asyncio
async def test_latest_pending_appointment_start_is_the_furthest_future_start_of_sent_reminders():
    near = row("near", starts_at=NOW + timedelta(hours=3), appointment_id="apt-1")
    far = row("far", starts_at=NOW + timedelta(hours=30), appointment_id="apt-2")

    repository = FakeAppointmentReminderRepository([near, far])

    assert (
        await repository.latest_pending_appointment_start(PHONE, now=NOW)
        == far.appointment_starts_at
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ignored",
    [
        row(status="pending"),
        row(status="skipped"),
        row(kind="review_request"),
        row(phone="+5491199999999"),
        row(starts_at=NOW),
        row(starts_at=NOW - timedelta(hours=1)),
        row(starts_at=None),
        # Unlike the reply context, an old send does not matter: only the start does.
    ],
)
async def test_latest_pending_appointment_start_ignores_non_pending_rows(ignored):
    repository = FakeAppointmentReminderRepository([ignored])

    assert await repository.latest_pending_appointment_start(PHONE, now=NOW) is None


@pytest.mark.asyncio
async def test_latest_pending_appointment_start_does_not_depend_on_the_send_age():
    old_send = row(sent_at=NOW - timedelta(hours=70))

    repository = FakeAppointmentReminderRepository([old_send])

    assert (
        await repository.latest_pending_appointment_start(PHONE, now=NOW)
        == old_send.appointment_starts_at
    )
