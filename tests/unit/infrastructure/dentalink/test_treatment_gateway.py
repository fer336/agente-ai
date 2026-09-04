import pytest

from app.domain.repositories.gateways import TreatmentGateway
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError
from app.infrastructure.dentalink.treatment_gateway import DentalinkTreatmentGateway


class _StubDentalinkClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.get_calls: list[str] = []

    async def get(self, path: str, params: dict[str, str] | None = None) -> object:
        self.get_calls.append(path)
        return self._responses[path]


@pytest.mark.asyncio
async def test_get_patient_treatments_calls_the_patient_scoped_endpoint():
    client = _StubDentalinkClient(
        {
            "/v1/pacientes/pat-1/tratamientos": [
                {
                    "id": 7998,
                    "id_paciente": "pat-1",
                    "nombre": "Nuevo plan de tratamiento",
                    "finalizado": 0,
                    "total": 1000,
                    "abonado": 400,
                    "deuda": 600,
                }
            ]
        }
    )
    gateway = DentalinkTreatmentGateway(client)

    treatments = await gateway.get_patient_treatments("pat-1")

    assert client.get_calls == ["/v1/pacientes/pat-1/tratamientos"]
    assert len(treatments) == 1
    treatment = treatments[0]
    assert treatment.id == "7998"
    assert treatment.patient_id == "pat-1"
    assert treatment.name == "Nuevo plan de tratamiento"
    assert treatment.is_finished is False
    assert treatment.total == 1000.0
    assert treatment.paid == 400.0
    assert treatment.debt == 600.0


@pytest.mark.asyncio
async def test_get_patient_treatments_maps_finalizado_true():
    client = _StubDentalinkClient(
        {
            "/v1/pacientes/pat-1/tratamientos": [
                {"id": 1, "id_paciente": "pat-1", "nombre": "Completo", "finalizado": 1}
            ]
        }
    )
    gateway = DentalinkTreatmentGateway(client)

    treatments = await gateway.get_patient_treatments("pat-1")

    assert treatments[0].is_finished is True
    assert treatments[0].total == 0.0


@pytest.mark.asyncio
async def test_get_patient_treatments_unwraps_data_envelope():
    client = _StubDentalinkClient(
        {
            "/v1/pacientes/pat-1/tratamientos": {
                "data": [{"id": 1, "id_paciente": "pat-1", "nombre": "Plan"}]
            }
        }
    )
    gateway = DentalinkTreatmentGateway(client)

    treatments = await gateway.get_patient_treatments("pat-1")

    assert [t.name for t in treatments] == ["Plan"]


@pytest.mark.asyncio
async def test_get_patient_treatments_raises_on_unexpected_shape():
    client = _StubDentalinkClient({"/v1/pacientes/pat-1/tratamientos": {"unexpected": "shape"}})
    gateway = DentalinkTreatmentGateway(client)

    with pytest.raises(DentalinkInvalidResponseError):
        await gateway.get_patient_treatments("pat-1")


def test_dentalink_treatment_gateway_satisfies_treatment_gateway_protocol():
    assert isinstance(DentalinkTreatmentGateway(_StubDentalinkClient({})), TreatmentGateway)
