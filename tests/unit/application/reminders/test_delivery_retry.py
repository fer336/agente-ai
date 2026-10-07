from datetime import timedelta

import pytest
from test_delivery import (
    NOW,
    Appointments,
    Messaging,
    Patients,
    ReminderRepository,
    appointment,
    patient,
    reminder,
    settings,
)

from app.application.reminders.delivery import deliver_due_reminders


@pytest.mark.asyncio
async def test_transient_failure_retries_then_exhausts_and_reclaims_stale_claim():
    row = reminder()
    repository = ReminderRepository([row])
    messaging = Messaging(RuntimeError("temporary"))
    delivery_settings = settings(batch_size=2, max_attempts=2, retry_backoff_seconds=3)
    await deliver_due_reminders(
        repository,
        Appointments([appointment()]),
        Patients(patient()),
        messaging,
        NOW,
        delivery_settings,
    )
    assert row.status == "pending" and row.due_at == NOW + timedelta(seconds=6)
    row.due_at = NOW
    await deliver_due_reminders(
        repository,
        Appointments([appointment()]),
        Patients(patient()),
        messaging,
        NOW,
        delivery_settings,
    )
    assert row.status == "failed"
    row.status, row.claimed_at = "processing", NOW - timedelta(seconds=61)
    assert (
        await deliver_due_reminders(
            repository,
            Appointments([appointment()]),
            Patients(patient()),
            Messaging(),
            NOW,
            delivery_settings,
        )
        == 1
    )
    assert row.status == "sent"
