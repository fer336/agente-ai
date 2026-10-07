"""Context note for the agent when a patient writes after an appointment reminder.

The reminder template is sent outside the agent's conversation and idle cleanup can
wipe its memory before the reply. This note tells the agent which appointment the
reminder was about, from the durable reminder row, only while that is still useful.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.application.reminders.template_message import spanish_date
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.value_objects.phone_number import PhoneNumber

#: How long after the send a reply is still read as an answer to the reminder.
REMINDER_REPLY_WINDOW = timedelta(hours=48)

_ASK_BY_KIND = {
    "confirm_day_before": ("le pedimos que confirme su asistencia con el botón «Confirmar turno»"),
    "confirm_or_location_same_day": (
        "le enviamos un recordatorio del mismo día sobre ese turno "
        "(confirmar o reprogramar, o cómo llegar si ya lo había confirmado)"
    ),
}


async def build_reminder_reply_context(
    reminders: AppointmentReminderRepository,
    phone: PhoneNumber,
    now: datetime,
    clinic_timezone: str,
) -> str | None:
    reminder = await reminders.find_latest_sent_pending_appointment_reminder(
        phone, sent_since=now - REMINDER_REPLY_WINDOW, now=now
    )
    if reminder is None or reminder.appointment_starts_at is None:
        return None
    starts_at = reminder.appointment_starts_at.astimezone(ZoneInfo(clinic_timezone))
    return (
        "Recordatorio de turno reciente: por WhatsApp le recordamos al paciente su turno del "
        f"{spanish_date(starts_at)} a las {starts_at.strftime('%H:%M')} y "
        f"{_ASK_BY_KIND[reminder.kind]}. Si su mensaje se refiere a ese turno (por ejemplo, avisa "
        "que no puede ir o quiere cambiarlo), respondé con ese contexto y no repitas el "
        "recordatorio."
    )
