import pytest

from app.domain.repositories.gateways import AgreementGateway
from app.infrastructure.dentalink.agreement_gateway import DentalinkAgreementGateway
from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkInvalidResponseError,
)


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
    client = _StubDentalinkClient({"/v1/pacientes/pat-1/convenios": [{"id": 1, "nombre": "OSDE"}]})
    gateway = DentalinkAgreementGateway(client)

    agreements = await gateway.get_patient_agreements("pat-1")

    assert [a.name for a in agreements] == ["OSDE"]
    assert client.get_calls == ["/v1/pacientes/pat-1/convenios"]


@pytest.mark.asyncio
async def test_link_patient_agreement_posts_to_the_patient_scoped_endpoint():
    client = _StubDentalinkClient({})
    gateway = DentalinkAgreementGateway(client)

    await gateway.link_patient_agreement("pat-1", "convenio-9")

    assert client.post_calls == [("/v1/pacientes/pat-1/convenios", {"id_convenio": "convenio-9"})]


class _RejectingPostClient(_StubDentalinkClient):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__({})
        self._error = DentalinkAPIError(status_code, body)

    async def post(self, path: str, json: object) -> object:
        self.post_calls.append((path, json))
        raise self._error


_ALREADY_LINKED = (
    '{"error":{"code":400,"message":"Paciente ID 4532 ya tiene el convenio ID 6 asociado"}}'
)


@pytest.mark.asyncio
async def test_link_patient_agreement_is_idempotent_when_the_patient_already_has_it():
    # Seen in production: re-registering a patient whose DNI already exists, or retrying
    # after a partial failure, makes Dentalink answer 400 "ya tiene el convenio".
    client = _RejectingPostClient(400, _ALREADY_LINKED)
    gateway = DentalinkAgreementGateway(client)

    await gateway.link_patient_agreement("4532", "6")

    assert client.post_calls == [("/v1/pacientes/4532/convenios", {"id_convenio": "6"})]


@pytest.mark.asyncio
async def test_link_patient_agreement_still_raises_when_the_message_names_another_agreement():
    gateway = DentalinkAgreementGateway(_RejectingPostClient(400, _ALREADY_LINKED))

    with pytest.raises(DentalinkAPIError):
        await gateway.link_patient_agreement("4532", "9")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, '{"error":{"code":400,"message":"Convenio inexistente"}}'),
        (500, _ALREADY_LINKED),
        (404, '{"error":{"code":404,"message":"Paciente no encontrado"}}'),
    ],
)
async def test_link_patient_agreement_raises_on_any_other_failure(status_code, body):
    gateway = DentalinkAgreementGateway(_RejectingPostClient(status_code, body))

    with pytest.raises(DentalinkAPIError):
        await gateway.link_patient_agreement("4532", "6")


def test_dentalink_agreement_gateway_satisfies_agreement_gateway_protocol():
    assert isinstance(DentalinkAgreementGateway(_StubDentalinkClient({})), AgreementGateway)
