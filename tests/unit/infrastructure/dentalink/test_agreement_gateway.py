import pytest

from app.domain.repositories.gateways import AgreementGateway
from app.infrastructure.dentalink.agreement_gateway import DentalinkAgreementGateway
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError


class _StubDentalinkClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, object]] = []

    async def get(self, path: str, params: dict[str, str] | None = None) -> object:
        self.get_calls.append(path)
        return self._responses[path]

    async def post(self, path: str, json: object) -> object:
        self.post_calls.append((path, json))
        return self._responses.get(path, {})


@pytest.mark.asyncio
async def test_list_agreements_maps_convenios_response():
    client = _StubDentalinkClient(
        {"/v1/convenios": [{"id": 1, "nombre": "OSDE"}, {"id": 2, "nombre": "Swiss Medical"}]}
    )
    gateway = DentalinkAgreementGateway(client)

    agreements = await gateway.list_agreements()

    assert [a.name for a in agreements] == ["OSDE", "Swiss Medical"]
    assert client.get_calls == ["/v1/convenios"]


@pytest.mark.asyncio
async def test_list_agreements_unwraps_data_envelope():
    client = _StubDentalinkClient({"/v1/convenios": {"data": [{"id": 1, "nombre": "OSDE"}]}})
    gateway = DentalinkAgreementGateway(client)

    agreements = await gateway.list_agreements()

    assert [a.name for a in agreements] == ["OSDE"]


@pytest.mark.asyncio
async def test_list_agreements_raises_on_unexpected_shape():
    client = _StubDentalinkClient({"/v1/convenios": {"unexpected": "shape"}})
    gateway = DentalinkAgreementGateway(client)

    with pytest.raises(DentalinkInvalidResponseError):
        await gateway.list_agreements()


@pytest.mark.asyncio
async def test_find_agreement_by_name_matches_case_insensitively():
    client = _StubDentalinkClient({"/v1/convenios": [{"id": 1, "nombre": "OSDE"}]})
    gateway = DentalinkAgreementGateway(client)

    found = await gateway.find_agreement_by_name("osde")

    assert found is not None
    assert found.id == "1"


@pytest.mark.asyncio
async def test_find_agreement_by_name_returns_none_when_no_match():
    client = _StubDentalinkClient({"/v1/convenios": [{"id": 1, "nombre": "OSDE"}]})
    gateway = DentalinkAgreementGateway(client)

    assert await gateway.find_agreement_by_name("Swiss Medical") is None


@pytest.mark.asyncio
async def test_get_patient_agreements_calls_the_patient_scoped_endpoint():
    client = _StubDentalinkClient(
        {"/v1/pacientes/pat-1/convenios": [{"id": 1, "nombre": "OSDE"}]}
    )
    gateway = DentalinkAgreementGateway(client)

    agreements = await gateway.get_patient_agreements("pat-1")

    assert [a.name for a in agreements] == ["OSDE"]
    assert client.get_calls == ["/v1/pacientes/pat-1/convenios"]


@pytest.mark.asyncio
async def test_link_patient_agreement_posts_to_the_patient_scoped_endpoint():
    client = _StubDentalinkClient({})
    gateway = DentalinkAgreementGateway(client)

    await gateway.link_patient_agreement("pat-1", "convenio-9")

    assert client.post_calls == [
        ("/v1/pacientes/pat-1/convenios", {"id_convenio": "convenio-9"})
    ]


def test_dentalink_agreement_gateway_satisfies_agreement_gateway_protocol():
    assert isinstance(DentalinkAgreementGateway(_StubDentalinkClient({})), AgreementGateway)
