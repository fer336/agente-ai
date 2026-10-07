"""Fail-closed application service for appointment-reminder button taps."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.application.reminders.action_payloads import (
    ReminderAction,
    ReminderActionKind,
    parse_reminder_action,
)
from app.domain.entities.appointment_reminder import AppointmentReminder, ReminderKind
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.gateways import (
    ReminderAppointment,
    ReminderAppointmentGateway,
    ReminderPatient,
    ReminderPatientGateway,
)
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import MENU_MAIN_PAYLOAD, OPERATION_CREATE_PAYLOAD
from app.domain.value_objects.phone_number import PhoneNumber

_SAFE_STALE_TEXT = "Este recordatorio ya no está disponible."
_CONFIRM_KINDS: frozenset[ReminderKind] = frozenset(
    {"confirm_day_before", "confirm_or_location_same_day"}
)
_LOCATION_KINDS: frozenset[ReminderKind] = frozenset({"confirm_or_location_same_day"})


@dataclass(frozen=True, slots=True)
class ReminderActionResult:
    handled: bool
    outcome: str
    text: str | None = None
    buttons: tuple[InteractiveButton, ...] = ()
    stale: bool = False
    location_requested: bool = False


class HandleReminderActionUseCase:
    def __init__(
        self,
        reminders: AppointmentReminderRepository,
        appointments: ReminderAppointmentGateway,
        patients: ReminderPatientGateway,
        contacts: ContactRepository,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._reminders = reminders
        self._appointments = appointments
        self._patients = patients
        self._contacts = contacts
        self._now = now

    async def handle(self, payload: str, inbound_phone: PhoneNumber) -> ReminderActionResult:
        action = parse_reminder_action(payload)
        if action is None:
            return ReminderActionResult(False, "not_handled")
        if action.kind is ReminderActionKind.REVIEW_OPTOUT:
            return await self._review_opt_out(inbound_phone)
        return await self._appointment_action(action, inbound_phone)

    async def _appointment_action(
        self, action: ReminderAction, inbound_phone: PhoneNumber
    ) -> ReminderActionResult:
        assert action.appointment_id is not None
        allowed_kinds = (
            _LOCATION_KINDS if action.kind is ReminderActionKind.LOCATION else _CONFIRM_KINDS
        )
        reminder = await self._reminders.find_sent_for_inbound_action(
            action.appointment_id, inbound_phone, allowed_kinds
        )
        if reminder is None:
            return _stale()
        appointment = await self._appointments.get_reminder_appointment(action.appointment_id)
        patient = await self._patients.get_reminder_patient(reminder.patient_id)
        if (
            appointment is None
            or patient is None
            or not _owns(reminder, appointment, patient, inbound_phone)
        ):
            return _stale()
        if appointment.state not in {"active", "confirmed"}:
            return _stale()
        if action.kind is ReminderActionKind.CONFIRM:
            if appointment.state == "confirmed":
                return ReminderActionResult(
                    True, "already_confirmed", "Tu turno ya estaba confirmado."
                )
            await self._appointments.mark_appointment_confirmed_via_patient_whatsapp(appointment.id)
            return ReminderActionResult(True, "confirmed", "Tu turno fue confirmado.")
        if action.kind is ReminderActionKind.CANCEL:
            return ReminderActionResult(
                True,
                "cancel_confirmation",
                "¿Querés cancelar tu turno?",
                (
                    InteractiveButton(f"REMINDER_CANCEL_CONFIRM:{appointment.id}", "Sí, cancelar"),
                    InteractiveButton(f"REMINDER_CANCEL_KEEP:{appointment.id}", "No, mantener"),
                ),
            )
        if action.kind is ReminderActionKind.CANCEL_CONFIRM:
            await self._appointments.cancel_appointment(
                appointment.id, f"reminder-cancel:{appointment.id}"
            )
            return ReminderActionResult(
                True,
                "cancelled",
                "Tu turno fue cancelado.",
                (
                    InteractiveButton(OPERATION_CREATE_PAYLOAD, "Agendar nuevo turno"),
                    InteractiveButton(MENU_MAIN_PAYLOAD, "Menú principal"),
                ),
            )
        if action.kind is ReminderActionKind.CANCEL_KEEP:
            return ReminderActionResult(True, "maintained", "Tu turno se mantiene.")
        return ReminderActionResult(True, "location", location_requested=True)

    async def _review_opt_out(self, inbound_phone: PhoneNumber) -> ReminderActionResult:
        if not await self._reminders.has_sent_review_request_for_recipient(inbound_phone):
            return _stale()
        if not await self._contacts.mark_review_opt_out(inbound_phone, self._now()):
            return _stale()
        return ReminderActionResult(
            True, "review_opted_out", "No te enviaremos más solicitudes de reseña."
        )


def _owns(
    reminder: AppointmentReminder,
    appointment: ReminderAppointment | None,
    patient: ReminderPatient | None,
    inbound_phone: PhoneNumber,
) -> bool:
    return bool(
        appointment is not None
        and patient is not None
        and appointment.id == reminder.appointment_id
        and appointment.patient_id == reminder.patient_id == patient.patient_id
        and patient.mobile == inbound_phone
    )


def _stale() -> ReminderActionResult:
    return ReminderActionResult(True, "stale", _SAFE_STALE_TEXT, stale=True)
