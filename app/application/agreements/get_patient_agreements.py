from app.domain.entities.agreement import Agreement
from app.domain.repositories.gateways import AgreementGateway


class GetPatientAgreementsUseCase:
    """Coordinates consulting a specific patient's registered agreement (PRD.md §19).

    Thin orchestration layer: depends only on the `AgreementGateway` port.
    Not wired into the graph yet — PRD.md §19's flow starts with "Identificar
    paciente" (§32), which this change's appointment/identification work
    defers to a follow-up (see this change's report). The use case is built
    now so that follow-up only has to wire it, not design it.
    """

    def __init__(self, gateway: AgreementGateway) -> None:
        self._gateway = gateway

    async def execute(self, patient_id: str) -> list[Agreement]:
        return await self._gateway.get_patient_agreements(patient_id)
