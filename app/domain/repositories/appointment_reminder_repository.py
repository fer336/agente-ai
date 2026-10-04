from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.appointment_reminder import AppointmentReminder


@runtime_checkable
class AppointmentReminderRepository(Protocol):
    """Port for durable, CAS-safe appointment reminder delivery state."""

    async def upsert(self, reminder: AppointmentReminder) -> bool:
        """Insert or refresh a reminder unless it was already sent.

        Returns whether an insert/update occurred. A sent row is immutable so
        repeated planning can never schedule it for delivery again.
        """
        ...

    async def list_due(self, now: datetime, limit: int) -> list[AppointmentReminder]: ...

    async def claim(self, reminder_id: str, claimed_at: datetime) -> bool: ...

    async def release_or_fail(
        self,
        reminder_id: str,
        *,
        claimed_at: datetime,
        error: str,
        retry_at: datetime | None,
    ) -> bool: ...

    async def mark_sent(
        self,
        reminder_id: str,
        *,
        claimed_at: datetime,
        external_message_id: str,
        sent_at: datetime,
    ) -> bool: ...

    async def has_sent_review_request_since(self, patient_id: str, cutoff: datetime) -> bool: ...
