from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.application.reminders.delivery import ReminderDeliverySettings, deliver_due_reminders
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.gateways import ReminderAppointment, ReminderPatient
from app.domain.value_objects.phone_number import PhoneNumber

NOW = datetime(2026, 10, 2, 13, tzinfo=UTC)
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
PHONE = PhoneNumber("+5491112345678")


class ReminderRepository:
    def __init__(self, rows=()):
        self.rows = {row.id: row for row in rows}
    async def list_due(self, now, limit):
        due = [row for row in self.rows.values() if row.status == "pending" and row.due_at <= now]
        return due[:limit]
    async def claim(self, reminder_id, claimed_at):
        row = self.rows[reminder_id]
        if row.status != "pending":
            return False
        row.status, row.claimed_at, row.attempts = "processing", claimed_at, row.attempts + 1
        return True
    async def reclaim_stale_claims(self, stale_before):
        count = 0
        for row in self.rows.values():
            if row.status == "processing" and row.claimed_at and row.claimed_at < stale_before:
                row.status, row.claimed_at = "pending", None
                count += 1
        return count
    async def skip_pending(self, reminder_id, *, reason, skipped_at):
        row = self.rows[reminder_id]
        if row.status != "pending":
            return False
        row.status, row.last_error = "skipped", reason
        return True
    async def renew_claim(self, reminder_id, *, claimed_at, renewed_at):
        row = self.rows[reminder_id]
        if row.status != "processing" or row.claimed_at != claimed_at:
            return False
        row.claimed_at = renewed_at
        self.last_renewed_at = renewed_at
        return True
    async def mark_skipped(self, reminder_id, *, claimed_at, reason, skipped_at):
        row = self.rows[reminder_id]
        if row.status != "processing" or row.claimed_at != claimed_at:
            return False
        row.status, row.claimed_at, row.last_error = "skipped", None, reason
        return True

    async def release_or_fail(self, reminder_id, *, claimed_at, error, retry_at):
        row = self.rows[reminder_id]
        if row.status != "processing" or row.claimed_at != claimed_at:
            return False
        status = "pending" if retry_at else "failed"
        row.status, row.claimed_at, row.last_error = status, None, error
        if retry_at:
            row.due_at = retry_at
        return True

    async def mark_sent(self, reminder_id, *, claimed_at, external_message_id, sent_at):
        row = self.rows[reminder_id]
        if row.status != "processing" or row.claimed_at != claimed_at:
            return False
        row.status, row.claimed_at = "sent", None
        row.external_message_id, row.sent_at = external_message_id, sent_at
        return True


class Appointments:
    def __init__(self, rows):
        self.rows = rows

    async def get_reminder_appointment(self, appointment_id):
        return next((row for row in self.rows if row.id == appointment_id), None)


class Patients:
    def __init__(self, value):
        self.value = value

    async def get_reminder_patient(self, patient_id):
        return self.value


class Messaging:
    def __init__(self, failure=None):
        self.sent = []
        self.failure = failure

    async def send_template(self, phone, template):
        if self.failure:
            raise self.failure
        self.sent.append((phone, template))
        return "external-1"


def appointment(state="active"):
    return ReminderAppointment(
        "apt-1", "patient-1", datetime(2026, 10, 3, 14, tzinfo=TZ), "1", state, state
    )


def patient(phone=PHONE):
    return ReminderPatient("patient-1", phone, "Ada")


def settings(**changes):
    values = {
        "template_language": "es_AR",
        "batch_size": 10,
        "max_attempts": 3,
        "claim_timeout_seconds": 60,
        "phone_allowlist": frozenset({str(PHONE)}),
    }
    values.update(changes)
    return ReminderDeliverySettings(**values)


def reminder(reminder_id="r1"):
    return AppointmentReminder(
        reminder_id, "apt-1", "patient-1", "confirm_day_before", "pending", NOW, str(PHONE)
    )


@pytest.mark.asyncio
async def test_delivery_sends_terminal_row_once():
    row = reminder()
    repository = ReminderRepository([row])
    messaging = Messaging()

    delivery_settings = settings(
        template_language="es_MX",
        confirmation_template_name="custom-confirm",
    )
    assert (
        await deliver_due_reminders(
            repository,
            Appointments([appointment()]),
            Patients(patient()),
            messaging,
            NOW,
            delivery_settings,
        )
        == 1
    )
    assert row.status == "sent"
    sent = messaging.sent[0][1]
    assert sent.name == "custom-confirm"
    assert sent.language == "es_MX"
    assert (
        await deliver_due_reminders(
            repository,
            Appointments([appointment()]),
            Patients(patient()),
            messaging,
            NOW,
            delivery_settings,
        )
        == 0
    )
    assert len(messaging.sent) == 1


@pytest.mark.asyncio
async def test_delivery_skips_stale_state_or_phone_mismatch_and_never_duplicates():
    row = reminder()
    repository, messaging = ReminderRepository([row]), Messaging()
    await deliver_due_reminders(
        repository,
        Appointments([appointment()]),
        Patients(patient(PhoneNumber("+5491199999999"))),
        messaging,
        NOW,
        settings(),
    )
    assert row.status == "skipped" and messaging.sent == []
    assert (
        await deliver_due_reminders(
            repository,
            Appointments([appointment()]),
            Patients(patient()),
            messaging,
            NOW,
            settings(),
        )
        == 0
    )

    stale = reminder("r2")
    stale_repository = ReminderRepository([stale])
    await deliver_due_reminders(
        stale_repository,
        Appointments([appointment("cancelled")]),
        Patients(patient()),
        messaging,
        NOW,
        settings(),
    )
    assert stale.status == "skipped"


@pytest.mark.asyncio
async def test_delivery_skips_recipient_removed_from_current_allowlist_before_claim():
    row = reminder()
    messaging = Messaging()
    await deliver_due_reminders(
        ReminderRepository([row]),
        Appointments([appointment()]),
        Patients(patient()),
        messaging,
        NOW,
        settings(phone_allowlist=frozenset()),
    )
    assert row.status == "skipped"
    assert messaging.sent == []


@pytest.mark.asyncio
async def test_renewed_claim_cannot_be_reclaimed_during_bounded_provider_send():
    row = reminder()
    repository = ReminderRepository([row])
    fresh_now = NOW + timedelta(seconds=30)

    class LeaseCheckingMessaging(Messaging):
        async def send_template(self, phone, template):
            assert repository.last_renewed_at == fresh_now
            assert await repository.reclaim_stale_claims(NOW + timedelta(seconds=1)) == 0
            return await super().send_template(phone, template)

    await deliver_due_reminders(
        repository,
        Appointments([appointment()]),
        Patients(patient()),
        LeaseCheckingMessaging(),
        NOW,
        settings(),
        utc_clock=lambda: fresh_now,
    )
    assert row.status == "sent"
