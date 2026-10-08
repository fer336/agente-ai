from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_reminder import ReminderKind
from app.domain.entities.patient import Patient


@dataclass(frozen=True)
class ReminderSettings:
    """The timing configuration needed by the pure reminder planner."""

    clinic_timezone: ZoneInfo | str
    day_before_time: time
    same_day_offset_hours: int
    send_window_start: time
    send_window_end: time
    review_time: time
    confirmation_template_name: str = "recordatorio_turno_confirmar"
    location_template_name: str = "recordatorio_turno_ubicacion"
    review_template_name: str = "solicitud_resena_google"
    unconfirmed_template_name: str = "recordatorio_turno_sin_confirmar"


@dataclass(frozen=True)
class ReminderCandidate:
    """A planned reminder before it is persisted as a delivery row."""

    appointment_id: str
    patient_id: str
    kind: ReminderKind
    due_at: datetime
    recipient_phone: str
    template_name: str


def plan_reminders(
    appointment: Appointment,
    patient: Patient,
    clinic_now: datetime,
    settings: ReminderSettings,
) -> list[ReminderCandidate]:
    """Plan reminders from clinic-local business times, persisting UTC instants.

    ``clinic_now`` is deliberately accepted by this pure boundary so callers
    provide one explicit clock and its local calendar context; scheduling is
    based on the appointment's clinic-local date rather than host-local time.
    """
    clinic_timezone = _clinic_timezone(settings.clinic_timezone)
    _clinic_local(clinic_now, clinic_timezone)
    start_at = _clinic_local(appointment.slot.time_range.start, clinic_timezone)
    appointment_id = str(appointment.id)
    recipient_phone = str(patient.phone)

    if appointment.status in {"active", "confirmed"}:
        day_before_due = datetime.combine(
            start_at.date() - timedelta(days=1),
            settings.day_before_time,
            tzinfo=clinic_timezone,
        )
        candidates = [
            ReminderCandidate(
                appointment_id=appointment_id,
                patient_id=patient.id,
                kind="confirm_day_before",
                due_at=day_before_due.astimezone(UTC),
                recipient_phone=recipient_phone,
                template_name=settings.confirmation_template_name,
            )
        ]
        same_day_due = start_at - timedelta(hours=settings.same_day_offset_hours)
        if (
            same_day_due.date() == start_at.date()
            and settings.send_window_start
            <= same_day_due.timetz().replace(tzinfo=None)
            <= settings.send_window_end
        ):
            candidates.append(
                ReminderCandidate(
                    appointment_id=appointment_id,
                    patient_id=patient.id,
                    kind="confirm_or_location_same_day",
                    due_at=same_day_due.astimezone(UTC),
                    recipient_phone=recipient_phone,
                    template_name=(
                        settings.location_template_name
                        if appointment.status == "confirmed"
                        else settings.unconfirmed_template_name
                    ),
                )
            )
        return candidates

    if appointment.status == "attended":
        review_due = datetime.combine(
            start_at.date() + timedelta(days=1),
            settings.review_time,
            tzinfo=clinic_timezone,
        )
        return [
            ReminderCandidate(
                appointment_id=appointment_id,
                patient_id=patient.id,
                kind="review_request",
                due_at=review_due.astimezone(UTC),
                recipient_phone=recipient_phone,
                template_name=settings.review_template_name,
            )
        ]

    return []


def _clinic_timezone(value: ZoneInfo | str) -> ZoneInfo:
    return ZoneInfo(value) if isinstance(value, str) else value


def _clinic_local(moment: datetime, clinic_timezone: ZoneInfo) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("Reminder planning requires timezone-aware datetimes")
    return moment.astimezone(clinic_timezone)
