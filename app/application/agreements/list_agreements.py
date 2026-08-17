from app.domain.entities.agreement import Agreement
from app.domain.repositories.gateways import AgreementGateway


class ListAgreementsUseCase:
    """Coordinates listing the clinic's configured agreements (PRD.md §18).

    Thin orchestration layer: depends only on the `AgreementGateway` port.
    """

    def __init__(self, gateway: AgreementGateway) -> None:
        self._gateway = gateway

    async def execute(self) -> list[Agreement]:
        return await self._gateway.list_agreements()
