from collections.abc import Collection, Iterable
from dataclasses import replace
from datetime import datetime

from app.domain.entities.appointment_reminder import (
    APPOINTMENT_REMINDER_KINDS,
    AppointmentReminder,
    ReminderKind,
)
from app.domain.value_objects.phone_number import PhoneNumber


class FakeAppointmentReminderRepository:
    """In-memory fake implementing `AppointmentReminderRepository` for tests and local dev."""

    def __init__(self, reminders: Iterable[AppointmentReminder] = ()) -> None:
        self.rows: dict[str, AppointmentReminder] = {row.id: row for row in reminders}

    async def upsert(self, reminder: AppointmentReminder) -> bool:
        for current in self.rows.values():
            if (current.appointment_id, current.kind) == (reminder.appointment_id, reminder.kind):
                if current.status not in ("pending", "failed"):
                    return False
                self.rows[current.id] = replace(
                    reminder, id=current.id, status="pending", attempts=0, sent_at=None
                )
                return True
        self.rows[reminder.id] = reminder
        return True

    async def list_due(self, now: datetime, limit: int) -> list[AppointmentReminder]:
        due = [r for r in self.rows.values() if r.status == "pending" and r.due_at <= now]
        return sorted(due, key=lambda r: r.due_at)[:limit]

    async def skip_pending(self, reminder_id: str, *, reason: str, skipped_at: datetime) -> bool:
        row = self.rows.get(reminder_id)
        if row is None or row.status != "pending":
            return False
        row.status, row.last_error = "skipped", reason
        return True

    async def claim(self, reminder_id: str, claimed_at: datetime) -> bool:
        row = self.rows.get(reminder_id)
        if row is None or row.status != "pending":
            return False
        row.status, row.claimed_at, row.attempts = "processing", claimed_at, row.attempts + 1
        return True

    async def renew_claim(
        self, reminder_id: str, *, claimed_at: datetime, renewed_at: datetime
    ) -> bool:
        row = self.rows.get(reminder_id)
        if row is None or row.status != "processing" or row.claimed_at != claimed_at:
            return False
        row.claimed_at = renewed_at
        return True

    async def reclaim_stale_claims(self, stale_before: datetime) -> int:
        stale = [
            r
            for r in self.rows.values()
            if r.status == "processing" and r.claimed_at is not None and r.claimed_at < stale_before
        ]
        for row in stale:
            row.status, row.claimed_at = "pending", None
        return len(stale)

    async def mark_skipped(
        self, reminder_id: str, *, claimed_at: datetime, reason: str, skipped_at: datetime
    ) -> bool:
        row = self._owned(reminder_id, claimed_at)
        if row is None:
            return False
        row.status, row.claimed_at, row.last_error = "skipped", None, reason
        return True

    async def release_or_fail(
        self, reminder_id: str, *, claimed_at: datetime, error: str, retry_at: datetime | None
    ) -> bool:
        row = self._owned(reminder_id, claimed_at)
        if row is None:
            return False
        row.status = "pending" if retry_at is not None else "failed"
        row.claimed_at, row.last_error = None, error
        if retry_at is not None:
            row.due_at = retry_at
        return True

    async def mark_sent(
        self, reminder_id: str, *, claimed_at: datetime, external_message_id: str, sent_at: datetime
    ) -> bool:
        row = self._owned(reminder_id, claimed_at)
        if row is None:
            return False
        row.status, row.claimed_at, row.last_error = "sent", None, None
        row.external_message_id, row.sent_at = external_message_id, sent_at
        return True

    async def has_sent_review_request_since(self, patient_id: str, cutoff: datetime) -> bool:
        return any(
            r.patient_id == patient_id
            and r.kind == "review_request"
            and r.status == "sent"
            and r.sent_at is not None
            and r.sent_at >= cutoff
            for r in self.rows.values()
        )

    async def find_sent_for_inbound_action(
        self,
        appointment_id: str,
        recipient_phone: PhoneNumber,
        allowed_kinds: Collection[ReminderKind],
    ) -> AppointmentReminder | None:
        for row in self.rows.values():
            if (
                row.appointment_id == appointment_id
                and row.recipient_phone == str(recipient_phone)
                and row.kind in allowed_kinds
                and row.status == "sent"
            ):
                return row
        return None

    async def has_sent_review_request_for_recipient(self, recipient_phone: PhoneNumber) -> bool:
        return any(
            r.recipient_phone == str(recipient_phone)
            and r.kind == "review_request"
            and r.status == "sent"
            for r in self.rows.values()
        )

    async def find_latest_sent_pending_appointment_reminder(
        self, recipient_phone: PhoneNumber, *, sent_since: datetime, now: datetime
    ) -> AppointmentReminder | None:
        matches = [
            r
            for r in self.rows.values()
            if r.recipient_phone == str(recipient_phone)
            and r.kind in APPOINTMENT_REMINDER_KINDS
            and r.status == "sent"
            and r.sent_at is not None
            and r.sent_at >= sent_since
            and r.appointment_starts_at is not None
            and r.appointment_starts_at > now
        ]
        return max(matches, key=lambda r: r.sent_at or sent_since, default=None)

    def _owned(self, reminder_id: str, claimed_at: datetime) -> AppointmentReminder | None:
        row = self.rows.get(reminder_id)
        if row is None or row.status != "processing" or row.claimed_at != claimed_at:
            return None
        return row
