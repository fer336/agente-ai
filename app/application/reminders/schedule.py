"""Bounded, fail-closed appointment reminder scheduling."""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.application.reminders.plan_reminders import ReminderSettings, plan_reminders
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.gateways import ReminderAppointmentGateway, ReminderPatientGateway
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReminderSchedulingSettings:
    enabled: bool
    phone_allowlist: set[str] | frozenset[str]
    clinic_timezone: ZoneInfo | str
    day_before_time: time
    same_day_offset_hours: int
    send_window_start: time
    send_window_end: time
    review_time: time
    review_cooldown_days: int


async def schedule_reminders(
    appointments: ReminderAppointmentGateway,
    patients: ReminderPatientGateway,
    repository: AppointmentReminderRepository,
    now: datetime,
    settings: ReminderSchedulingSettings,
    contact_preferences: ContactRepository | None = None,
) -> int:
    """Plan yesterday through tomorrow, with no external call unless enabled."""
    if not settings.enabled or not settings.phone_allowlist:
        return 0
    timezone = (
        ZoneInfo(settings.clinic_timezone)
        if isinstance(settings.clinic_timezone, str)
        else settings.clinic_timezone
    )
    local_now = now.astimezone(timezone)
    rows = await appointments.list_reminder_appointments_for_date_window(
        local_now.date() - timedelta(days=1), local_now.date() + timedelta(days=1)
    )
    inserted = 0
    planner_settings = ReminderSettings(
        timezone,
        settings.day_before_time,
        settings.same_day_offset_hours,
        settings.send_window_start,
        settings.send_window_end,
        settings.review_time,
    )
    for source in rows:
        try:
            patient = await patients.get_reminder_patient(source.patient_id)
            if (
                patient is None
                or patient.patient_id != source.patient_id
                or str(patient.mobile) not in settings.phone_allowlist
            ):
                continue
            appointment = Appointment(
                AppointmentId(source.id),
                source.patient_id,
                AppointmentSlot(
                    source.id,
                    "",
                    "",
                    DateTimeRange(source.starts_at, source.starts_at + timedelta(minutes=1)),
                ),
                source.state,
            )
            planner_patient = Patient(patient.patient_id, patient.display_name, patient.mobile)
            candidates = plan_reminders(appointment, planner_patient, now, planner_settings)
        except (ValueError, TypeError):
            logger.warning("appointment_reminder.schedule_invalid appointment_id=%s", source.id)
            continue
        for candidate in candidates:
            if candidate.kind == "review_request" and (
                (
                    contact_preferences is not None
                    and await contact_preferences.is_review_opted_out(
                        PhoneNumber(candidate.recipient_phone)
                    )
                )
                or await repository.has_sent_review_request_since(
                    candidate.patient_id, now - timedelta(days=settings.review_cooldown_days)
                )
            ):
                continue
            reminder = AppointmentReminder(
                id=str(uuid4()),
                appointment_id=candidate.appointment_id,
                patient_id=candidate.patient_id,
                kind=candidate.kind,
                status="pending",
                due_at=candidate.due_at,
                recipient_phone=candidate.recipient_phone,
            )
            if await repository.upsert(reminder):
                inserted += 1
    return inserted
