import json

import httpx
import pytest

import app.infrastructure.dentalink.client as client_module
from app.domain.exceptions.errors import PatientAlreadyExistsError
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.exceptions import DentalinkAPIError
from app.infrastructure.dentalink.patient_gateway import DentalinkPatientGateway, _build_q_param

_VALID_DNI = "30111222"


def _client_with_responses(
    monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]
) -> tuple[DentalinkClient, list[httpx.Request]]:
    captured: list[httpx.Request] = []
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return remaining.pop(0)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )
    return client, captured


@pytest.mark.asyncio
async def test_find_patient_returns_none_for_a_dni_that_is_not_well_formed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, captured = _client_with_responses(monkeypatch, [])
    gateway = DentalinkPatientGateway(client)

    found = await gateway.find_patient("Maria Soto", "not-a-dni")

    assert found is None
    assert captured == []  # never calls Dentalink for an unvalidatable DNI


@pytest.mark.asyncio
async def test_find_patient_filters_by_rut_field_using_the_confirmed_q_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": 28,
                    "rut": "30111222",
                    "nombre": "Maria",
                    "apellidos": "Soto",
                    "celular": "1122334455",
                }
            ]
        },
    )
    client, captured = _client_with_responses(monkeypatch, [response])
    gateway = DentalinkPatientGateway(client)

    found = await gateway.find_patient("Maria Soto", _VALID_DNI)

    assert found is not None
    assert found.id == "28"
    assert found.phone == PhoneNumber("+5491122334455")
    q_param = captured[0].url.params["q"]
    assert json.loads(q_param) == {"rut": {"eq": "30111222"}}


@pytest.mark.asyncio
async def test_find_patient_returns_none_when_name_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        json={
            "data": [
                {"id": 28, "rut": "30111222", "nombre": "Maria", "apellidos": "Soto",
                 "celular": "1122334455"}
            ]
        },
    )
    client, _ = _client_with_responses(monkeypatch, [response])
    gateway = DentalinkPatientGateway(client)

    found = await gateway.find_patient("Otro Nombre", _VALID_DNI)

    assert found is None


@pytest.mark.asyncio
async def test_create_patient_sends_split_name_and_normalized_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_response = httpx.Response(200, json={"data": []})
    create_response = httpx.Response(201, json={"id": 99})
    client, captured = _client_with_responses(
        monkeypatch, [search_response, create_response]
    )
    gateway = DentalinkPatientGateway(client)

    created = await gateway.create_patient(
        "Maria Soto Perez", _VALID_DNI, PhoneNumber("+5491122334455")
    )

    assert created.id == "99"
    assert created.dni == _VALID_DNI
    create_request = captured[1]
    assert create_request.method == "POST"
    body = json.loads(create_request.content)
    assert body == {
        "rut": "30111222",
        "nombre": "Maria",
        "apellidos": "Soto Perez",
        "celular": "5491122334455",
    }


@pytest.mark.asyncio
async def test_create_patient_raises_a_typed_conflict_instead_of_duplicating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_response = httpx.Response(
        200,
        json={
            "data": [
                {"id": 28, "rut": "30111222", "nombre": "Maria", "apellidos": "Soto",
                 "celular": "1122334455"}
            ]
        },
    )
    client, captured = _client_with_responses(monkeypatch, [search_response])
    gateway = DentalinkPatientGateway(client)

    with pytest.raises(PatientAlreadyExistsError) as exc_info:
        await gateway.create_patient("Maria Soto", _VALID_DNI, PhoneNumber("+5491122334455"))

    assert exc_info.value.existing_patient_id == "28"
    assert len(captured) == 1  # never issues the POST once a conflict is found


@pytest.mark.asyncio
async def test_create_patient_rejects_an_invalid_dni_before_any_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, captured = _client_with_responses(monkeypatch, [])
    gateway = DentalinkPatientGateway(client)

    with pytest.raises(ValueError, match="DNI"):
        await gateway.create_patient("Maria Soto", "not-a-dni", PhoneNumber("+5491122334455"))

    assert captured == []


def test_build_q_param_rejects_a_field_outside_the_allow_list():
    with pytest.raises(ValueError, match="not allowed"):
        _build_q_param({"comentario": ("eq", "'; DROP TABLE pacientes; --")})


def test_build_q_param_rejects_an_operator_outside_the_allow_list():
    with pytest.raises(ValueError, match="not allowed"):
        _build_q_param({"rut": ("gt", "30111222")})


def test_build_q_param_carries_untrusted_text_only_as_a_json_value():
    # A value containing JSON-structure-looking characters must stay a
    # single JSON string value, never get parsed back out as structure.
    params = _build_q_param({"nombre": ("lk", '"}, "rut": {"eq": "0-0')})

    decoded = json.loads(params["q"])
    assert decoded == {"nombre": {"lk": '"}, "rut": {"eq": "0-0'}}


@pytest.mark.asyncio
async def test_dentalink_api_error_never_includes_the_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(500, text="internal error, no such patient")
    client, captured = _client_with_responses(monkeypatch, [response])
    gateway = DentalinkPatientGateway(client)

    with pytest.raises(DentalinkAPIError) as exc_info:
        await gateway.find_patient("Maria Soto", _VALID_DNI)

    assert "secret-token" not in str(exc_info.value)
    assert "secret-token" not in repr(exc_info.value)
    assert len(captured) == 1  # a non-timeout error is never retried
