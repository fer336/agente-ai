from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange


class SearchAvailabilityUseCase:
    """Coordinates an appointment-availability search (architecture doc §5.3).

    Thin orchestration layer: it knows nothing about Dentalink or any other
    concrete integration — it depends only on the `AppointmentGateway` port.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
    ) -> list[AppointmentSlot]:
        return await self._gateway.search_availability(
            specialty_id=specialty_id,
            professional_id=professional_id,
            date_range=date_range,
        )
