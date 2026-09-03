import pytest

from app.domain.repositories.gateways import SpecialtyGateway
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError
from app.infrastructure.dentalink.specialty_gateway import DentalinkSpecialtyGateway


class _StubDentalinkClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.get_calls: list[str] = []

    async def get(self, path: str, params: dict[str, str] | None = None) -> object:
        self.get_calls.append(path)
        return self._responses[path]


@pytest.mark.asyncio
async def test_list_specialties_maps_especialidades_response():
    client = _StubDentalinkClient(
        {
            "/v1/especialidades": [
                {"id": 1, "nombre": "Ortodoncia"},
                {"id": 2, "nombre": "Endodoncia"},
            ]
        }
    )
    gateway = DentalinkSpecialtyGateway(client)

    specialties = await gateway.list_specialties()

    assert [s.name for s in specialties] == ["Ortodoncia", "Endodoncia"]
    assert client.get_calls == ["/v1/especialidades"]


@pytest.mark.asyncio
async def test_list_specialties_unwraps_data_envelope():
    client = _StubDentalinkClient(
        {"/v1/especialidades": {"data": [{"id": 1, "nombre": "Ortodoncia"}]}}
    )
    gateway = DentalinkSpecialtyGateway(client)

    specialties = await gateway.list_specialties()

    assert [s.name for s in specialties] == ["Ortodoncia"]


@pytest.mark.asyncio
async def test_list_specialties_raises_on_unexpected_shape():
    client = _StubDentalinkClient({"/v1/especialidades": {"unexpected": "shape"}})
    gateway = DentalinkSpecialtyGateway(client)

    with pytest.raises(DentalinkInvalidResponseError):
        await gateway.list_specialties()


def test_dentalink_specialty_gateway_satisfies_specialty_gateway_protocol():
    assert isinstance(DentalinkSpecialtyGateway(_StubDentalinkClient({})), SpecialtyGateway)
