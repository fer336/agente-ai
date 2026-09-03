from app.domain.entities.specialty import Specialty
from app.domain.repositories.gateways import SpecialtyGateway


class ListSpecialtiesUseCase:
    """Coordinates listing the clinic's configured dental specialties (PRD.md §27.1).

    Thin orchestration layer: depends only on the `SpecialtyGateway` port.
    """

    def __init__(self, gateway: SpecialtyGateway) -> None:
        self._gateway = gateway

    async def execute(self) -> list[Specialty]:
        return await self._gateway.list_specialties()
