"""Appointment-reminder polling worker."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.conversations.start_fresh_session import StartFreshSessionUseCase
from app.application.reminders.delivery import ReminderDeliverySettings, deliver_due_reminders
from app.application.reminders.schedule import ReminderSchedulingSettings, schedule_reminders
from app.config.settings import Settings
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.gateways import (
    MessagingGateway,
    ReminderAppointmentGateway,
    ReminderPatientGateway,
)
from app.domain.value_objects.phone_number import PhoneNumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppointmentReminderWorkerRepositories:
    """Session-bound repositories used by one reminder-worker tick."""

    reminders: AppointmentReminderRepository
    contacts: ContactRepository
    start_fresh_session: StartFreshSessionUseCase | None = None


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
    start_fresh_session: StartFreshSessionUseCase | None = None,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Run bounded scheduling then delivery once."""
    if not settings.appointment_reminders_recipient_policy.can_run(
        enabled=settings.appointment_reminders_enabled
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
            settings.appointment_reminders_recipient_policy,
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
            settings.appointment_reminders_recipient_policy,
            settings.appointment_reminders_unconfirmed_template_name,
        ),
        on_sent=_review_sent_hook(start_fresh_session),
    )
    return scheduled, delivered


def _review_sent_hook(
    start_fresh_session: StartFreshSessionUseCase | None,
) -> Callable[[AppointmentReminder, PhoneNumber], Awaitable[None]] | None:
    if start_fresh_session is None:
        return None

    async def on_review_sent(reminder: AppointmentReminder, phone: PhoneNumber) -> None:
        outcome = await start_fresh_session.execute(phone)
        logger.info(
            "appointment_reminder_worker.fresh_session reminder_id=%s outcome=%s",
            reminder.id,
            outcome,
        )

    return on_review_sent


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
                    start_fresh_session=repositories.start_fresh_session,
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
