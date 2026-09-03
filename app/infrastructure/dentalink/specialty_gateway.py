from app.domain.entities.specialty import Specialty
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.schemas import as_list, specialty_from_especialidad


class DentalinkSpecialtyGateway:
    """`DentalinkClient`-based real implementation of the `SpecialtyGateway` port.

    UNVERIFIED against a live Dentalink account (no live credentials in this
    environment). PRD.md §27.1's endpoint table documents `GET
    /v1/especialidades` with certainty; the response JSON shape below
    follows this module's existing `agreement_from_convenio`-style
    conservative `id`/`nombre` mapping — confirm against a real Dentalink
    payload before production use.
    """

    def __init__(self, client: DentalinkClient) -> None:
        self._client = client

    async def list_specialties(self) -> list[Specialty]:
        raw_especialidades = await self._client.get("/v1/especialidades")
        return [specialty_from_especialidad(raw) for raw in as_list(raw_especialidades)]
