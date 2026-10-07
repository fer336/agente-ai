from datetime import UTC, datetime, timedelta

import pytest

from app.application.reminders.reply_context import build_reminder_reply_context
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_appointment_reminder_repository import (
    FakeAppointmentReminderRepository,
)

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
PHONE = PhoneNumber("+5491112345678")
TZ = "America/Argentina/Buenos_Aires"
# 2026-10-08 10:30 in Buenos Aires.
STARTS_AT = datetime(2026, 10, 8, 13, 30, tzinfo=UTC)


def row(kind="confirm_day_before", *, sent_at=NOW - timedelta(hours=1), starts_at=STARTS_AT):
    return AppointmentReminder(
        "r-1",
        "apt-1",
        "patient-1",
        kind,
        "sent",
        NOW,
        str(PHONE),
        sent_at=sent_at,
        appointment_starts_at=starts_at,
    )


async def context(*rows):
    return await build_reminder_reply_context(
        FakeAppointmentReminderRepository(list(rows)), PHONE, NOW, TZ
    )


@pytest.mark.asyncio
async def test_day_before_context_names_the_appointment_in_clinic_time_and_the_ask():
    note = await context(row())

    assert note is not None
    assert "jueves 8 de octubre" in note
    assert "10:30" in note
    assert "confirm" in note.lower()


@pytest.mark.asyncio
async def test_same_day_context_names_the_appointment():
    note = await context(row("confirm_or_location_same_day"))

    assert note is not None
    assert "jueves 8 de octubre" in note and "10:30" in note
    assert "mismo día" in note


@pytest.mark.asyncio
async def test_no_context_after_48_hours():
    assert await context(row(sent_at=NOW - timedelta(hours=49))) is None


@pytest.mark.asyncio
async def test_context_is_kept_up_to_the_48_hour_boundary():
    assert await context(row(sent_at=NOW - timedelta(hours=47, minutes=59))) is not None


@pytest.mark.asyncio
async def test_no_context_once_the_appointment_has_passed_or_its_start_is_unknown():
    assert await context(row(starts_at=NOW - timedelta(minutes=1))) is None
    assert await context(row(starts_at=None)) is None


@pytest.mark.asyncio
async def test_no_context_without_a_sent_reminder():
    assert await context() is None
