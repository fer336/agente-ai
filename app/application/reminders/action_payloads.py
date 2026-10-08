"""Parse deterministic reminder callback payloads without side effects."""

from dataclasses import dataclass
from enum import StrEnum


class ReminderActionKind(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    CANCEL_CONFIRM = "cancel_confirm"
    CANCEL_KEEP = "cancel_keep"
    LOCATION = "location"
    RESCHEDULE = "reschedule"
    REVIEW_OPTOUT = "review_optout"


@dataclass(frozen=True, slots=True)
class ReminderAction:
    kind: ReminderActionKind
    appointment_id: str | None = None


_PREFIXES = (
    ("REMINDER_CANCEL_CONFIRM:", ReminderActionKind.CANCEL_CONFIRM),
    ("REMINDER_CANCEL_KEEP:", ReminderActionKind.CANCEL_KEEP),
    ("REMINDER_CONFIRM:", ReminderActionKind.CONFIRM),
    ("REMINDER_CANCEL:", ReminderActionKind.CANCEL),
    ("REMINDER_LOCATION:", ReminderActionKind.LOCATION),
    ("REMINDER_RESCHEDULE:", ReminderActionKind.RESCHEDULE),
)


def parse_reminder_action(payload: str) -> ReminderAction | None:
    if payload == "REMINDER_REVIEW_OPTOUT":
        return ReminderAction(ReminderActionKind.REVIEW_OPTOUT)
    for prefix, kind in _PREFIXES:
        if payload.startswith(prefix):
            appointment_id = payload.removeprefix(prefix)
            if appointment_id and ":" not in appointment_id:
                return ReminderAction(kind, appointment_id)
    return None
