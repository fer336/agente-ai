from datetime import datetime

import pytest

from app.domain.entities.tool_execution import COMPLETED, FAILED
from app.domain.exceptions.errors import AppointmentNotFoundError
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.appointment_gateway import DentalinkAppointmentGateway
from app.infrastructure.dentalink.exceptions import DentalinkAPIError, DentalinkInvalidResponseError
from app.infrastructure.observability.trace_context import TraceContext, use_trace_context
from tests.fixtures.gateways import (
    make_error_repository,
    make_error_service,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_patient, make_slot


class _StubDentalinkClient:
    def __init__(
        self,
        get_responses: dict[str, object] | None = None,
        raises_on: dict[tuple[str, str], DentalinkAPIError] | None = None,
    ) -> None:
        self._get_responses = get_responses or {}
        self._raises_on = raises_on or {}
        self.get_calls: list[tuple[str, dict[str, str] | None]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.put_calls: list[tuple[str, dict[str, object]]] = []
        self.post_response: object = {"id": 1, "id_paciente": "pat-1"}
        self.put_response: object = {}

    async def get(self, path: str, params: dict[str, str] | None = None) -> object:
        self.get_calls.append((path, params))
        key = ("GET", path)
        if key in self._raises_on:
            raise self._raises_on[key]
        return self._get_responses.get(path, [])

    async def post(self, path: str, json: dict[str, object]) -> object:
        self.post_calls.append((path, json))
        key = ("POST", path)
        if key in self._raises_on:
            raise self._raises_on[key]
        return self.post_response

    async def put(self, path: str, json: dict[str, object]) -> object:
        self.put_calls.append((path, json))
        key = ("PUT", path)
        if key in self._raises_on:
            raise self._raises_on[key]
        return self.put_response


def _gateway(client: _StubDentalinkClient) -> DentalinkAppointmentGateway:
    return DentalinkAppointmentGateway(
        client,
        default_branch_id="1",
        default_chair_id="5",
        default_duration_minutes=30,
    )


@pytest.mark.asyncio
async def test_search_availability_issues_one_request_for_a_single_day_range():
    client = _StubDentalinkClient(
        get_responses={
            "/v5/agendas": [
                {
                    "id": "slot-1",
                    "id_profesional": "626",
                    "id_especialidad": "cleaning",
                    "fecha": "2026-08-15",
                    "hora_inicio": "15:30",
                    "duracion": 30,
                }
            ]
        }
    )
    gateway = _gateway(client)

    slots = await gateway.search_availability(
        specialty_id="cleaning",
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 16, 0, 0)),
    )

    assert len(client.get_calls) == 1
    path, params = client.get_calls[0]
    assert path == "/v5/agendas"
    assert params == {
        "filtro[id_sucursal][eq]": "1",
        "filtro[fecha][eq]": "2026-08-15",
        "filtro[duracion][eq]": "30",
    }
    assert [s.id for s in slots] == ["slot-1"]


@pytest.mark.asyncio
async def test_search_availability_filters_out_non_matching_specialty():
    client = _StubDentalinkClient(
        get_responses={
            "/v5/agendas": [
                {
                    "id": "slot-1",
                    "id_profesional": "626",
                    "id_especialidad": "whitening",
                    "fecha": "2026-08-15",
                    "hora_inicio": "15:30",
                }
            ]
        }
    )
    gateway = _gateway(client)

    slots = await gateway.search_availability(
        specialty_id="cleaning",
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 16, 0, 0)),
    )

    assert slots == []


@pytest.mark.asyncio
async def test_search_availability_includes_professional_filter_when_given():
    client = _StubDentalinkClient(get_responses={"/v5/agendas": []})
    gateway = _gateway(client)

    await gateway.search_availability(
        specialty_id=None,
        professional_id="626",
        date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 16, 0, 0)),
    )

    _, params = client.get_calls[0]
    assert params is not None
    assert params["filtro[id_profesional][eq]"] == "626"


@pytest.mark.asyncio
async def test_search_availability_issues_one_request_per_calendar_day():
    client = _StubDentalinkClient(get_responses={"/v5/agendas": []})
    gateway = _gateway(client)

    await gateway.search_availability(
        specialty_id=None,
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 18, 0, 0)),
    )

    dates_queried = [params["filtro[fecha][eq]"] for _, params in client.get_calls if params]
    # date_range is half-open [start, end) — end=2026-08-18T00:00 excludes
    # the 18th itself, so only 15/16/17 are queried.
    assert dates_queried == ["2026-08-15", "2026-08-16", "2026-08-17"]


@pytest.mark.asyncio
async def test_list_professionals_maps_dentistas_response():
    client = _StubDentalinkClient(
        get_responses={
            "/v1/dentistas": [
                {"id_dentista": 626, "nombre": "Dra. Laura Pérez", "id_especialidad": "cleaning"},
                {"id_dentista": 900, "nombre": "Dr. Roe", "id_especialidad": "whitening"},
            ]
        }
    )
    gateway = _gateway(client)

    professionals = await gateway.list_professionals(specialty_id="cleaning")

    assert [p.id for p in professionals] == ["626"]


@pytest.mark.asyncio
async def test_get_patient_appointments_resolves_status_from_estados():
    client = _StubDentalinkClient(
        get_responses={
            "/v1/citas/estados": [
                {"id": 1, "nombre": "Confirmada"},
                {"id": 9, "nombre": "Anulada"},
            ],
            "/v1/pacientes/pat-1/citas": [
                {
                    "id": 10,
                    "id_paciente": "pat-1",
                    "id_dentista": "626",
                    "fecha": "2026-08-15",
                    "hora_inicio": "10:00",
                    "id_estado": 9,
                },
                {
                    "id": 11,
                    "id_paciente": "pat-1",
                    "id_dentista": "626",
                    "fecha": "2026-08-16",
                    "hora_inicio": "10:00",
                    "id_estado": 1,
                },
            ],
        }
    )
    gateway = _gateway(client)

    appointments = await gateway.get_patient_appointments("pat-1")

    statuses = {str(a.id): a.status for a in appointments}
    assert statuses == {"10": "cancelled", "11": "confirmed"}


@pytest.mark.asyncio
async def test_create_appointment_sends_the_documented_required_fields():
    client = _StubDentalinkClient()
    client.post_response = {
        "id": 55,
        "id_paciente": "pat-1",
        "id_dentista": "prof-1",
        "fecha": "2026-08-01",
        "hora_inicio": "10:00",
        "duracion": 30,
    }
    gateway = _gateway(client)
    slot = make_slot()
    patient = make_patient(id_="pat-1")

    appointment = await gateway.create_appointment(patient, slot, idempotency_key="key-1")

    assert client.post_calls[0][0] == "/v1/citas/"
    payload = client.post_calls[0][1]
    assert payload == {
        "id_dentista": "prof-1",
        "id_especialidad": "cleaning",
        "id_sucursal": "1",
        "id_sillon": "5",
        "id_paciente": "pat-1",
        "fecha": "2026-08-01",
        "hora_inicio": "10:00",
        "duracion": 30,
    }
    assert str(appointment.id) == "55"


@pytest.mark.asyncio
async def test_reschedule_appointment_uses_id_sesion_field_name():
    client = _StubDentalinkClient()
    client.post_response = {
        "id": 55,
        "id_paciente": "pat-1",
        "fecha": "2026-08-02",
        "hora_inicio": "11:00",
    }
    gateway = _gateway(client)
    new_slot = make_slot(
        id_="slot-2", start=datetime(2026, 8, 2, 11, 0), end=datetime(2026, 8, 2, 11, 30)
    )

    appointment = await gateway.reschedule_appointment("55", new_slot, idempotency_key="key-2")

    assert client.post_calls[0][0] == "/v1/citas/changeDate"
    payload = client.post_calls[0][1]
    assert payload["id_sesion"] == "55"
    assert "id_cita" not in payload
    assert str(appointment.id) == "55"


@pytest.mark.asyncio
async def test_reschedule_appointment_raises_not_found_on_404():
    client = _StubDentalinkClient(
        raises_on={("POST", "/v1/citas/changeDate"): DentalinkAPIError(404, "not found")}
    )
    gateway = _gateway(client)

    with pytest.raises(AppointmentNotFoundError):
        await gateway.reschedule_appointment("missing", make_slot(), idempotency_key="key-1")


@pytest.mark.asyncio
async def test_cancel_appointment_resolves_state_id_then_puts_it():
    client = _StubDentalinkClient(
        get_responses={
            "/v1/citas/estados": [
                {"id": 1, "nombre": "Confirmada"},
                {"id": 9, "nombre": "Anulada"},
            ]
        }
    )
    gateway = _gateway(client)

    await gateway.cancel_appointment("55", idempotency_key="key-1")

    assert client.put_calls == [("/v1/citas/55", {"id_estado": "9"})]


@pytest.mark.asyncio
async def test_cancel_appointment_caches_the_resolved_state_id_across_calls():
    client = _StubDentalinkClient(
        get_responses={"/v1/citas/estados": [{"id": 9, "nombre": "Anulada"}]}
    )
    gateway = _gateway(client)

    await gateway.cancel_appointment("55", idempotency_key="key-1")
    await gateway.cancel_appointment("56", idempotency_key="key-2")

    assert len([c for c in client.get_calls if c[0] == "/v1/citas/estados"]) == 1


@pytest.mark.asyncio
async def test_cancel_appointment_raises_invalid_response_when_no_cancellation_state_found():
    client = _StubDentalinkClient(
        get_responses={"/v1/citas/estados": [{"id": 1, "nombre": "Confirmada"}]}
    )
    gateway = _gateway(client)

    with pytest.raises(DentalinkInvalidResponseError):
        await gateway.cancel_appointment("55", idempotency_key="key-1")


@pytest.mark.asyncio
async def test_cancel_appointment_raises_not_found_on_404():
    client = _StubDentalinkClient(
        get_responses={"/v1/citas/estados": [{"id": 9, "nombre": "Anulada"}]},
        raises_on={("PUT", "/v1/citas/missing"): DentalinkAPIError(404, "not found")},
    )
    gateway = _gateway(client)

    with pytest.raises(AppointmentNotFoundError):
        await gateway.cancel_appointment("missing", idempotency_key="key-1")


def test_dentalink_appointment_gateway_satisfies_appointment_gateway_protocol():
    assert isinstance(_gateway(_StubDentalinkClient()), AppointmentGateway)


@pytest.mark.asyncio
async def test_search_availability_records_a_completed_tool_execution():
    client = _StubDentalinkClient(get_responses={"/v5/agendas": []})
    gateway = _gateway(client)
    tool_execution_repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(),
    )

    with use_trace_context(context):
        await gateway.search_availability(
            specialty_id="cleaning",
            professional_id=None,
            date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 16, 0, 0)),
        )

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.tool_name == "SearchAvailabilityTool"
    assert execution.provider == "dentalink"
    assert execution.operation == "search_availability"
    assert execution.status == COMPLETED
    assert execution.node_execution_id == "ne-1"
    assert execution.response_summary == "0 slots"


@pytest.mark.asyncio
async def test_reschedule_appointment_records_a_failed_tool_execution_on_404():
    client = _StubDentalinkClient(
        raises_on={("POST", "/v1/citas/changeDate"): DentalinkAPIError(404, "not found")}
    )
    gateway = _gateway(client)
    tool_execution_repository = make_tool_execution_repository()
    error_repository = make_error_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(error_repository),
    )

    with use_trace_context(context), pytest.raises(AppointmentNotFoundError):
        await gateway.reschedule_appointment("missing", make_slot(), idempotency_key="key-1")

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].tool_name == "RescheduleAppointmentTool"
    assert executions[0].status == FAILED
    assert executions[0].http_status == "404"
    assert executions[0].response_summary is None
    error = await error_repository.get_by_id(executions[0].error_id)
    assert error is not None
    assert error.error_type == "appointment_not_found"


@pytest.mark.asyncio
async def test_search_availability_does_not_record_anything_outside_a_trace_context():
    client = _StubDentalinkClient(get_responses={"/v5/agendas": []})
    gateway = _gateway(client)

    slots = await gateway.search_availability(
        specialty_id=None,
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 15, 0, 0), datetime(2026, 8, 16, 0, 0)),
    )

    assert slots == []
