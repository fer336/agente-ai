"""Pure approved-template selection for appointment reminders."""

from datetime import datetime

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.gateways import (
    ReminderAppointment,
    ReminderPatient,
    TemplateMessage,
    TemplateQuickReplyButton,
)


def build_template_message(
    reminder: AppointmentReminder,
    appointment: ReminderAppointment,
    patient: ReminderPatient,
    *,
    language: str,
    confirmation_template_name: str,
    location_template_name: str,
    review_template_name: str,
    unconfirmed_template_name: str,
) -> TemplateMessage | None:
    """Build only the dynamic parts of one approved WhatsApp template."""
    time_label = appointment.starts_at.strftime("%H:%M")
    if reminder.kind == "confirm_day_before" and appointment.state in {"active", "confirmed"}:
        return TemplateMessage(
            confirmation_template_name,
            language,
            (patient.display_name, spanish_date(appointment.starts_at), time_label),
            (TemplateQuickReplyButton(0, f"REMINDER_CONFIRM:{appointment.id}"),),
        )
    if reminder.kind == "confirm_or_location_same_day" and appointment.state == "confirmed":
        return TemplateMessage(
            location_template_name,
            language,
            (patient.display_name, time_label),
            (TemplateQuickReplyButton(0, f"REMINDER_LOCATION:{appointment.id}"),),
        )
    if reminder.kind == "confirm_or_location_same_day" and appointment.state == "active":
        return TemplateMessage(
            unconfirmed_template_name,
            language,
            (patient.display_name, spanish_date(appointment.starts_at), time_label),
            (
                TemplateQuickReplyButton(0, f"REMINDER_CONFIRM:{appointment.id}"),
                TemplateQuickReplyButton(1, f"REMINDER_RESCHEDULE:{appointment.id}"),
            ),
        )
    if reminder.kind == "review_request" and appointment.state == "attended":
        return TemplateMessage(
            review_template_name,
            language,
            (patient.display_name,),
            # The approved review template has a static URL at index 0.
            (TemplateQuickReplyButton(1, "REMINDER_REVIEW_OPTOUT"),),
        )
    return None


def spanish_date(value: datetime) -> str:
    months = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
        "septiembre", "octubre", "noviembre", "diciembre",
    )
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    return f"{weekdays[value.weekday()]} {value.day} de {months[value.month - 1]}"
