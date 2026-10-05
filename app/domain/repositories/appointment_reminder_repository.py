from collections.abc import Collection
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.appointment_reminder import AppointmentReminder, ReminderKind
from app.domain.value_objects.phone_number import PhoneNumber


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

    async def skip_pending(
        self, reminder_id: str, *, reason: str, skipped_at: datetime
    ) -> bool: ...

    async def claim(self, reminder_id: str, claimed_at: datetime) -> bool: ...

    async def renew_claim(
        self, reminder_id: str, *, claimed_at: datetime, renewed_at: datetime
    ) -> bool:
        """CAS-refreshes the ownership token immediately before provider I/O."""
        ...

    async def reclaim_stale_claims(self, stale_before: datetime) -> int: ...

    async def mark_skipped(
        self, reminder_id: str, *, claimed_at: datetime, reason: str, skipped_at: datetime
    ) -> bool: ...

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

    async def find_sent_for_inbound_action(
        self,
        appointment_id: str,
        recipient_phone: PhoneNumber,
        allowed_kinds: Collection[ReminderKind],
    ) -> AppointmentReminder | None:
        """Returns only a terminal sent reminder eligible for an inbound action."""
        ...

    async def has_sent_review_request_for_recipient(self, recipient_phone: PhoneNumber) -> bool:
        """Whether this normalized recipient was sent a terminal review request."""
        ...
