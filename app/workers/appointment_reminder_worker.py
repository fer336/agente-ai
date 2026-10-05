"""Appointment-reminder polling worker."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.reminders.delivery import ReminderDeliverySettings, deliver_due_reminders
from app.application.reminders.schedule import ReminderSchedulingSettings, schedule_reminders
from app.config.settings import Settings
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.gateways import (
    MessagingGateway,
    ReminderAppointmentGateway,
    ReminderPatientGateway,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppointmentReminderWorkerRepositories:
    """Session-bound repositories used by one reminder-worker tick."""

    reminders: AppointmentReminderRepository
    contacts: ContactRepository


AppointmentReminderWorkerRepositoriesProvider = Callable[
    [], AbstractAsyncContextManager[AppointmentReminderWorkerRepositories]
]


async def run_appointment_reminder_tick(
    repository: AppointmentReminderRepository,
    appointments: ReminderAppointmentGateway,
    patients: ReminderPatientGateway,
    messaging: MessagingGateway,
    settings: Settings,
    *,
    contacts: ContactRepository | None = None,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Run bounded scheduling then delivery once."""
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
        contacts,
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


async def run_appointment_reminder_loop(
    repositories_provider: AppointmentReminderWorkerRepositoriesProvider,
    appointments: ReminderAppointmentGateway,
    patients: ReminderPatientGateway,
    messaging: MessagingGateway,
    settings: Settings,
    *,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Poll reminders with a fresh repository session each tick.

    A failed tick is logged and retried after the bounded interval; cancellation
    remains observable to the application lifespan.
    """
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        try:
            async with repositories_provider() as repositories:
                scheduled, delivered = await run_appointment_reminder_tick(
                    repositories.reminders,
                    appointments,
                    patients,
                    messaging,
                    settings,
                    contacts=repositories.contacts,
                    now=datetime.now(UTC),
                )
                logger.info(
                    "appointment_reminder_worker.tick_completed scheduled=%d delivered=%d",
                    scheduled,
                    delivered,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - worker must survive a failed tick
            logger.exception(
                "appointment_reminder_worker.tick_failed error_type=%s", type(exc).__name__
            )
        iterations += 1
        if max_iterations is None or iterations < max_iterations:
            await asyncio.sleep(interval_seconds)
