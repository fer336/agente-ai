from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ReminderKind = Literal[
    "confirm_day_before",
    "confirm_or_location_same_day",
    "review_request",
]
ReminderStatus = Literal["pending", "processing", "sent", "skipped", "failed"]


@dataclass
class AppointmentReminder:
    """Durable delivery state for one idempotent appointment reminder."""

    id: str
    appointment_id: str
    patient_id: str
    kind: ReminderKind
    status: ReminderStatus
    due_at: datetime
    recipient_phone: str = field(repr=False)
    attempts: int = 0
    claimed_at: datetime | None = None
    external_message_id: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    #: Start of the appointment the reminder is about. Nullable: rows scheduled before
    #: this column existed (or by older code) do not know it.
    appointment_starts_at: datetime | None = None
