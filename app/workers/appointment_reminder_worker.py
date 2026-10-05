"""One unwired appointment-reminder worker tick; T5 owns scheduler startup."""

from datetime import UTC, datetime

from app.application.reminders.delivery import ReminderDeliverySettings, deliver_due_reminders
from app.application.reminders.schedule import ReminderSchedulingSettings, schedule_reminders
from app.config.settings import Settings
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.gateways import (
    MessagingGateway,
    ReminderAppointmentGateway,
    ReminderPatientGateway,
)


async def run_appointment_reminder_tick(
    repository: AppointmentReminderRepository,
    appointments: ReminderAppointmentGateway,
    patients: ReminderPatientGateway,
    messaging: MessagingGateway,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Run bounded scheduling then delivery once; intentionally not started by main."""
    if (
        not settings.appointment_reminders_enabled
        or not settings.appointment_reminders_phone_allowlist_set
    ):
        return (0, 0)
    current = now or datetime.now(UTC)
    scheduled = await schedule_reminders(
        appointments,
        patients,
        repository,
        current,
        ReminderSchedulingSettings(
            True,
            settings.appointment_reminders_phone_allowlist_set,
            settings.clinic_timezone,
            settings.appointment_reminders_day_before_time,
            settings.appointment_reminders_same_day_offset_hours,
            settings.appointment_reminders_send_window_start,
            settings.appointment_reminders_send_window_end,
            settings.appointment_reminders_review_time,
            settings.appointment_reminders_review_cooldown_days,
        ),
    )
    delivered = await deliver_due_reminders(
        repository,
        appointments,
        patients,
        messaging,
        current,
        ReminderDeliverySettings(
            settings.appointment_reminders_template_language,
            settings.appointment_reminders_batch_size,
            settings.appointment_reminders_max_attempts,
            settings.appointment_reminders_claim_timeout_seconds,
            settings.appointment_reminders_retry_backoff_seconds,
            settings.appointment_reminders_confirmation_template_name,
            settings.appointment_reminders_location_template_name,
            settings.appointment_reminders_review_template_name,
            settings.appointment_reminders_phone_allowlist_set,
        ),
    )
    return scheduled, delivered
