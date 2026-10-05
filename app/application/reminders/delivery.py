"""CAS-safe appointment-reminder delivery orchestration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.application.reminders.template_message import build_template_message
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.gateways import (
    MessagingGateway,
    ReminderAppointment,
    ReminderAppointmentGateway,
    ReminderPatient,
    ReminderPatientGateway,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReminderDeliverySettings:
    template_language: str
    batch_size: int
    max_attempts: int
    claim_timeout_seconds: int
    retry_backoff_seconds: int = 60
    confirmation_template_name: str = "recordatorio_turno_confirmar"
    location_template_name: str = "recordatorio_turno_ubicacion"
    review_template_name: str = "solicitud_resena_google"
    phone_allowlist: frozenset[str] = frozenset()


async def deliver_due_reminders(
    repository: AppointmentReminderRepository,
    appointments: ReminderAppointmentGateway,
    patients: ReminderPatientGateway,
    messaging: MessagingGateway,
    now: datetime,
    settings: ReminderDeliverySettings,
    *,
    utc_clock: Callable[[], datetime] | None = None,
) -> int:
    await repository.reclaim_stale_claims(now - timedelta(seconds=settings.claim_timeout_seconds))
    handled = 0
    for reminder in await repository.list_due(now, settings.batch_size):
        if reminder.recipient_phone not in settings.phone_allowlist:
            await repository.skip_pending(
                reminder.id, reason="recipient_not_allowlisted", skipped_at=now
            )
            logger.info(
                "appointment_reminder.skipped reminder_id=%s reason=recipient_not_allowlisted",
                reminder.id,
            )
            continue
        if not await repository.claim(reminder.id, now):
            continue
        handled += 1
        ownership_claimed_at = now
        try:
            current = await appointments.get_reminder_appointment(reminder.appointment_id)
            patient = await patients.get_reminder_patient(reminder.patient_id)
            if current is None or patient is None or not _matches(reminder, current, patient):
                await repository.mark_skipped(
                    reminder.id,
                    claimed_at=ownership_claimed_at,
                    reason="stale_or_mismatch",
                    skipped_at=now,
                )
                logger.info(
                    "appointment_reminder.skipped reminder_id=%s reason=stale_or_mismatch",
                    reminder.id,
                )
                continue
            template = build_template_message(
                reminder,
                current,
                patient,
                language=settings.template_language,
                confirmation_template_name=settings.confirmation_template_name,
                location_template_name=settings.location_template_name,
                review_template_name=settings.review_template_name,
            )
            if template is None:
                await repository.mark_skipped(
                    reminder.id,
                    claimed_at=ownership_claimed_at,
                    reason="ineligible_state",
                    skipped_at=now,
                )
                logger.info(
                    "appointment_reminder.skipped reminder_id=%s reason=ineligible_state",
                    reminder.id,
                )
                continue
            # A database lease prevents concurrent workers, but a crash after
            # provider acceptance cannot be exactly-once without a YCloud idempotency key.
            # Terminal DB rows are never claimed or sent again.
            renewed_at = utc_clock() if utc_clock is not None else datetime.now(UTC)
            if renewed_at <= ownership_claimed_at:
                # Tests and callers may pass an explicit logical tick time;
                # retain a strictly newer CAS token even when clocks differ.
                renewed_at = ownership_claimed_at + timedelta(microseconds=1)
            if not await repository.renew_claim(
                reminder.id, claimed_at=ownership_claimed_at, renewed_at=renewed_at
            ):
                continue
            ownership_claimed_at = renewed_at
            external_id = await messaging.send_template(patient.mobile, template)
            await repository.mark_sent(
                reminder.id,
                claimed_at=ownership_claimed_at,
                external_message_id=external_id,
                sent_at=now,
            )
            logger.info(
                "appointment_reminder.sent reminder_id=%s kind=%s", reminder.id, reminder.kind
            )
        except Exception as exc:
            # Integration failures are retryable; deterministic data checks are handled above.
            retry_at = (
                now
                + timedelta(
                    seconds=settings.retry_backoff_seconds * (2 ** max(reminder.attempts, 0))
                )
                if reminder.attempts < settings.max_attempts
                else None
            )
            await repository.release_or_fail(
                reminder.id,
                claimed_at=ownership_claimed_at,
                error=type(exc).__name__,
                retry_at=retry_at,
            )
            logger.warning(
                "appointment_reminder.delivery_failed reminder_id=%s error_type=%s retry=%s",
                reminder.id,
                type(exc).__name__,
                retry_at is not None,
            )
    return handled


def _matches(
    reminder: AppointmentReminder,
    appointment: ReminderAppointment,
    patient: ReminderPatient,
) -> bool:
    return bool(
        appointment.id == reminder.appointment_id
        and appointment.patient_id == reminder.patient_id
        and patient.patient_id == reminder.patient_id
        and str(patient.mobile) == reminder.recipient_phone
    )

