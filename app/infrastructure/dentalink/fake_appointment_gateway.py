from datetime import date

from app.domain.repositories.gateways import ReminderAppointment


class FakeReminderAppointmentGateway:
    """In-memory read-only reminder appointment gateway for focused tests."""

    def __init__(self, appointments: list[ReminderAppointment] | None = None) -> None:
        self._appointments = list(appointments) if appointments else []

    async def list_reminder_appointments_for_date_window(
        self, start_date: date, end_date: date
    ) -> list[ReminderAppointment]:
        return [
            appointment
            for appointment in self._appointments
            if start_date <= appointment.starts_at.date() <= end_date
        ]
