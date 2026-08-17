from app.domain.entities.agreement import Agreement
from app.domain.repositories.gateways import AgreementGateway


class FindAgreementByNameUseCase:
    """Coordinates looking up a single agreement by name (PRD.md §18).

    Thin orchestration layer: depends only on the `AgreementGateway` port.
    """

    def __init__(self, gateway: AgreementGateway) -> None:
        self._gateway = gateway

    async def execute(self, name: str) -> Agreement | None:
        return await self._gateway.find_agreement_by_name(name)
