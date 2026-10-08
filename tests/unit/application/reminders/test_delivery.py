from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.application.reminders.delivery import ReminderDeliverySettings, deliver_due_reminders
from app.application.reminders.recipient_policy import ReminderRecipientPolicy
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
        "recipient_policy": ReminderRecipientPolicy("allowlist", frozenset({str(PHONE)})),
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
        settings(recipient_policy=ReminderRecipientPolicy("allowlist", frozenset())),
    )
    assert row.status == "skipped"
    assert messaging.sent == []


@pytest.mark.asyncio
async def test_delivery_all_mode_sends_with_an_empty_allowlist():
    row = reminder()
    messaging = Messaging()

    assert (
        await deliver_due_reminders(
            ReminderRepository([row]),
            Appointments([appointment()]),
            Patients(patient()),
            messaging,
            NOW,
            settings(recipient_policy=ReminderRecipientPolicy("all", frozenset())),
        )
        == 1
    )
    assert row.status == "sent"
    assert len(messaging.sent) == 1


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


def review_reminder():
    return AppointmentReminder(
        "r-review", "apt-1", "patient-1", "review_request", "pending", NOW, str(PHONE)
    )


async def _deliver(row, on_sent, state="attended", messaging=None):
    repository = ReminderRepository([row])
    await deliver_due_reminders(
        repository,
        Appointments([appointment(state)]),
        Patients(patient()),
        messaging or Messaging(),
        NOW,
        settings(),
        on_sent=on_sent,
    )
    return repository


@pytest.mark.asyncio
async def test_on_sent_runs_after_mark_sent_for_review_request_only():
    calls = []

    async def on_sent(reminder, phone):
        calls.append((reminder.id, reminder.status, phone))

    await _deliver(review_reminder(), on_sent)
    await _deliver(reminder(), on_sent, state="active")

    assert calls == [("r-review", "sent", PHONE)]


@pytest.mark.asyncio
async def test_on_sent_is_not_called_when_the_send_fails_or_is_skipped():
    calls = []

    async def on_sent(reminder, phone):
        calls.append(reminder.id)

    await _deliver(review_reminder(), on_sent, messaging=Messaging(RuntimeError("boom")))
    await _deliver(review_reminder(), on_sent, state="active")

    assert calls == []


@pytest.mark.asyncio
async def test_on_sent_failure_never_changes_reminder_state_or_stops_the_tick():
    async def on_sent(reminder, phone):
        raise RuntimeError("reset failed")

    row = review_reminder()
    repository = await _deliver(row, on_sent)

    assert row.status == "sent"
    assert row.last_error is None
    assert row.attempts == 1
    assert repository.rows["r-review"].status == "sent"


async def _deliver_with_hooks(
    row, *, record_sent=None, on_sent=None, state="active", messaging=None
):
    repository = ReminderRepository([row])
    await deliver_due_reminders(
        repository,
        Appointments([appointment(state)]),
        Patients(patient()),
        messaging or Messaging(),
        NOW,
        settings(),
        record_sent=record_sent,
        on_sent=on_sent,
    )
    return repository


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "state"),
    [(reminder(), "active"), (review_reminder(), "attended")],
)
async def test_record_sent_runs_after_mark_sent_for_every_kind(row, state):
    calls = []

    async def record_sent(reminder, phone, template):
        calls.append((reminder.id, reminder.status, phone, template.name))

    await _deliver_with_hooks(row, record_sent=record_sent, state=state)

    assert len(calls) == 1
    assert calls[0][1:3] == ("sent", PHONE)


@pytest.mark.asyncio
async def test_record_sent_is_not_called_when_the_send_fails_or_is_skipped():
    calls = []

    async def record_sent(reminder, phone, template):
        calls.append(reminder.id)

    await _deliver_with_hooks(
        reminder(), record_sent=record_sent, messaging=Messaging(RuntimeError("boom"))
    )
    await _deliver_with_hooks(review_reminder(), record_sent=record_sent, state="active")

    assert calls == []


@pytest.mark.asyncio
async def test_record_sent_failure_never_changes_the_reminder_or_skips_the_review_cleanup():
    cleanup = []

    async def record_sent(reminder, phone, template):
        raise RuntimeError("database unavailable")

    async def on_sent(reminder, phone):
        cleanup.append(reminder.id)

    row = review_reminder()
    repository = await _deliver_with_hooks(
        row, record_sent=record_sent, on_sent=on_sent, state="attended"
    )

    assert (row.status, row.last_error, row.attempts) == ("sent", None, 1)
    assert repository.rows["r-review"].status == "sent"
    assert cleanup == ["r-review"]


@pytest.mark.asyncio
async def test_record_sent_runs_before_the_review_cleanup():
    order = []

    async def record_sent(reminder, phone, template):
        order.append("record")

    async def on_sent(reminder, phone):
        order.append("cleanup")

    await _deliver_with_hooks(
        review_reminder(), record_sent=record_sent, on_sent=on_sent, state="attended"
    )

    assert order == ["record", "cleanup"]
