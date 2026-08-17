from app.domain.entities.agreement import Agreement
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.schemas import agreement_from_convenio, as_list


class DentalinkAgreementGateway:
    """`DentalinkClient`-based real implementation of the `AgreementGateway` port.

    UNVERIFIED against a live Dentalink account (no live credentials in this
    environment). Not wired into DI yet — see `DentalinkAppointmentGateway`'s
    docstring for the same swap-point convention.
    """

    def __init__(self, client: DentalinkClient) -> None:
        self._client = client

    async def list_agreements(self) -> list[Agreement]:
        raw_convenios = await self._client.get("/v1/convenios")
        return [agreement_from_convenio(raw) for raw in as_list(raw_convenios)]

    async def find_agreement_by_name(self, name: str) -> Agreement | None:
        # PRD.md §18's flow is client-side matching against the full
        # convenios list — no server-side name-search endpoint is
        # documented in §27.1's table.
        normalized = name.strip().casefold()
        for agreement in await self.list_agreements():
            if agreement.name.strip().casefold() == normalized:
                return agreement
        return None

    async def get_patient_agreements(self, patient_id: str) -> list[Agreement]:
        raw_convenios = await self._client.get(f"/v1/pacientes/{patient_id}/convenios")
        return [agreement_from_convenio(raw) for raw in as_list(raw_convenios)]
