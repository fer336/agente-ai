from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.repositories.gateways import AppointmentGateway


class RescheduleAppointmentUseCase:
    """Coordinates rescheduling a confirmed appointment (PRD.md §13's last step).

    Thin orchestration layer: depends only on the `AppointmentGateway` port.
    Callers are responsible for everything PRD.md §11/§13 require BEFORE
    this runs — explicit confirmation received, availability revalidated,
    the Redis superposition lock held (see
    `RevalidateAndRescheduleAppointmentUseCase`, which wraps this with
    exactly that sequence, mirroring `RevalidateAndCreateAppointmentUseCase`).
    This use case never decides on its own whether it's safe to run — it
    only makes the final `AppointmentGateway` call. PRD.md §13's last
    paragraph: uses Dentalink's dedicated "change date" operation
    (`AppointmentGateway.reschedule_appointment`), never a delete+create.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(
        self, appointment_id: str, new_slot: AppointmentSlot, idempotency_key: str
    ) -> Appointment:
        return await self._gateway.reschedule_appointment(appointment_id, new_slot, idempotency_key)
