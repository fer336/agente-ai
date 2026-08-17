from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.repositories.gateways import AppointmentGateway


class CreateAppointmentUseCase:
    """Coordinates creating a confirmed appointment (PRD.md §10's last step).

    Thin orchestration layer: depends only on the `AppointmentGateway`
    port. Callers are responsible for everything PRD.md §10-11 require
    BEFORE this runs — explicit confirmation received, availability
    revalidated, the Redis superposition lock held (see
    `RevalidateAndCreateAppointmentUseCase`, which wraps this with exactly
    that sequence). This use case never decides on its own whether it's
    safe to run — it only makes the final `AppointmentGateway` call.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, patient: Patient, slot: AppointmentSlot, idempotency_key: str
    ) -> Appointment:
        return await self._gateway.create_appointment(patient, slot, idempotency_key)
