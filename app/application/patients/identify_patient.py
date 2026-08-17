from app.domain.entities.patient import Patient
from app.domain.repositories.gateways import PatientGateway


class IdentifyPatientUseCase:
    """Coordinates identifying a patient by full name + DNI (PRD.md §32).

    Thin orchestration layer: depends only on the `PatientGateway` port.
    Returns `None` when no match is found — callers decide the messaging
    (PRD.md doesn't mandate a specific "not found" response) and whether to
    offer a retry or derive to administración.
    """

    def __init__(self, gateway: PatientGateway) -> None:
        self._gateway = gateway

    async def execute(self, full_name: str, dni: str) -> Patient | None:
        return await self._gateway.find_patient(full_name, dni)
