from datetime import date

from app.domain.repositories.gateways import ReminderAppointment


class FakeReminderAppointmentGateway:
    """In-memory read-only reminder appointment gateway for focused tests."""

    def __init__(self, appointments: list[ReminderAppointment] | None = None) -> None:
        self._appointments = list(appointments) if appointments else []
        self.patient_whatsapp_confirmation_calls: list[str] = []
        self.cancellation_calls: list[tuple[str, str]] = []

    async def list_reminder_appointments_for_date_window(
        self, start_date: date, end_date: date
    ) -> list[ReminderAppointment]:
        return [
            appointment
            for appointment in self._appointments
            if start_date <= appointment.starts_at.date() <= end_date
        ]

    async def get_reminder_appointment(self, appointment_id: str) -> ReminderAppointment | None:
        return next((item for item in self._appointments if item.id == appointment_id), None)

    async def mark_appointment_confirmed_via_patient_whatsapp(self, appointment_id: str) -> None:
        self.patient_whatsapp_confirmation_calls.append(appointment_id)

    async def cancel_appointment(self, appointment_id: str, idempotency_key: str) -> None:
        self.cancellation_calls.append((appointment_id, idempotency_key))
