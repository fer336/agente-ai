from itertools import count

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.exceptions.errors import AppointmentNotFoundError
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange


class FakeDentalinkGateway:
    """In-memory fake implementing `AppointmentGateway` for local dev and tests."""

    def __init__(
        self,
        available_slots: list[AppointmentSlot] | None = None,
        professionals: list[Professional] | None = None,
    ) -> None:
        self._available_slots = list(available_slots) if available_slots else []
        self._professionals = list(professionals) if professionals else []
        self._appointments_by_key: dict[str, Appointment] = {}
        self._appointments_by_id: dict[str, Appointment] = {}
        self._next_id = count(1)

    async def search_availability(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
    ) -> list[AppointmentSlot]:
        return [
            slot
            for slot in self._available_slots
            if (specialty_id is None or slot.specialty_id == specialty_id)
            and (professional_id is None or slot.professional_id == professional_id)
            and date_range.contains(slot.time_range.start)
        ]

    async def list_professionals(self, specialty_id: str | None = None) -> list[Professional]:
        return [
            professional
            for professional in self._professionals
            if specialty_id is None or professional.specialty_id == specialty_id
        ]

    async def get_patient_appointments(self, patient_id: str) -> list[Appointment]:
        return [
            appointment
            for appointment in self._appointments_by_id.values()
            if appointment.patient_id == patient_id and appointment.status != "cancelled"
        ]

    async def create_appointment(
        self,
        patient: Patient,
        slot: AppointmentSlot,
        idempotency_key: str,
    ) -> Appointment:
        if idempotency_key in self._appointments_by_key:
            return self._appointments_by_key[idempotency_key]

        appointment = Appointment(
            id=AppointmentId(str(next(self._next_id))),
            patient_id=patient.id,
            slot=slot,
            status="confirmed",
        )
        self._appointments_by_key[idempotency_key] = appointment
        self._appointments_by_id[str(appointment.id)] = appointment
        return appointment

    async def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot: AppointmentSlot,
        idempotency_key: str,
    ) -> Appointment:
        existing = self.get_appointment(appointment_id)
        if existing is None:
            raise AppointmentNotFoundError(appointment_id)

        rescheduled = Appointment(
            id=existing.id,
            patient_id=existing.patient_id,
            slot=new_slot,
            status="confirmed",
        )
        self._appointments_by_key[idempotency_key] = rescheduled
        self._appointments_by_id[str(rescheduled.id)] = rescheduled
        return rescheduled

    async def cancel_appointment(self, appointment_id: str, idempotency_key: str) -> None:
        existing = self.get_appointment(appointment_id)
        if existing is None:
            raise AppointmentNotFoundError(appointment_id)

        cancelled = Appointment(
            id=existing.id,
            patient_id=existing.patient_id,
            slot=existing.slot,
            status="cancelled",
        )
        self._appointments_by_key[idempotency_key] = cancelled
        self._appointments_by_id[str(cancelled.id)] = cancelled

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        """Test/dev introspection helper — not part of the `AppointmentGateway` Protocol."""
        return self._appointments_by_id.get(appointment_id)
