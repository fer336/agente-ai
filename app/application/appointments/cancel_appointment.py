from app.domain.repositories.gateways import AppointmentGateway


class CancelAppointmentUseCase:
    """Coordinates cancelling a confirmed appointment (PRD.md §14's last step).

    Thin orchestration layer: depends only on the `AppointmentGateway` port.
    Unlike `RevalidateAndCreateAppointmentUseCase`, there is no lock or
    revalidation step here — cancelling has no slot to race over (PRD.md
    §14 never mentions revalidating availability before cancelling, only
    confirming then calling Dentalink). Callers are responsible for
    everything PRD.md §14 requires BEFORE this runs — explicit confirmation
    received.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(self, appointment_id: str, idempotency_key: str) -> None:
        await self._gateway.cancel_appointment(appointment_id, idempotency_key)
