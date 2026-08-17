from app.domain.entities.appointment import Appointment
from app.domain.repositories.gateways import AppointmentGateway


class GetPatientAppointmentsUseCase:
    """Coordinates listing a patient's upcoming appointments (PRD.md §13-14's
    "Consultar próximas citas" step).

    Thin orchestration layer: depends only on the `AppointmentGateway` port.
    Filters out already-`cancelled` appointments — `reschedule`/`cancel`
    only make sense against a still-active appointment, and the real
    `DentalinkAppointmentGateway.get_patient_appointments` returns the
    patient's full history rather than pre-filtering it (see that gateway's
    own docstring for its PRD.md §27.1-§27.5 best-effort mapping).
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(self, patient_id: str) -> list[Appointment]:
        appointments = await self._gateway.get_patient_appointments(patient_id)
        return [appointment for appointment in appointments if appointment.status != "cancelled"]
