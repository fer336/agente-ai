import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import (
    get_committing_error_query_service,
    get_conversation_query_service,
    get_error_query_service,
    get_graph_state_query_service,
    get_kpi_name_catalog,
    get_kpi_query_service,
    get_run_query_service,
)
from app.api.dependencies.gateways import get_agreement_gateway, get_ycloud_client
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.graph_state_queries import GraphStateQueryService
from app.application.admin.kpi_names import KpiNameCatalog
from app.application.admin.kpi_queries import KpiQueryService
from app.application.admin.run_queries import RunQueryService
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.domain.entities.agreement import Agreement
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.ycloud.exceptions import YCloudAPIError
from app.main import app
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_agreement_gateway,
    make_conversation_repository,
    make_error_repository,
    make_message_repository,
    make_node_execution_repository,
    make_pending_action_repository,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_conversation,
    make_error_record,
    make_message,
    make_node_execution,
    make_pending_action,
    make_tool_execution,
)

_SECRET = "test-admin-secret"
_TTL = 3600


def _override_settings() -> Settings:
    return Settings(admin_session_secret=_SECRET, admin_session_ttl_seconds=_TTL, _env_file=None)


@dataclass
class _AdminFakes:
    conversations: object
    messages: object
    agent_runs: object
    errors: object
    node_executions: object
    tool_executions: object
    pending_actions: object


@pytest.fixture(autouse=True)
def _override_admin_dependencies() -> _AdminFakes:
    app.dependency_overrides[get_settings] = _override_settings

    conversations = make_conversation_repository()
    messages = make_message_repository()
    agent_runs = make_agent_run_repository()
    errors = make_error_repository()
    node_executions = make_node_execution_repository()
    tool_executions = make_tool_execution_repository()
    pending_actions = make_pending_action_repository()

    conversation_service = ConversationQueryService(conversations, messages, agent_runs, errors)
    error_service = ErrorQueryService(errors)
    run_service = RunQueryService(agent_runs, node_executions, tool_executions)
    graph_state_service = GraphStateQueryService(node_executions)
    kpi_service = KpiQueryService(pending_actions, tool_executions)

    app.dependency_overrides[get_conversation_query_service] = lambda: conversation_service
    app.dependency_overrides[get_error_query_service] = lambda: error_service
    app.dependency_overrides[get_committing_error_query_service] = lambda: error_service
    app.dependency_overrides[get_run_query_service] = lambda: run_service
    app.dependency_overrides[get_graph_state_query_service] = lambda: graph_state_service
    app.dependency_overrides[get_kpi_query_service] = lambda: kpi_service
    app.dependency_overrides[get_kpi_name_catalog] = lambda: _name_catalog()

    yield _AdminFakes(
        conversations=conversations,
        messages=messages,
        agent_runs=agent_runs,
        errors=errors,
        node_executions=node_executions,
        tool_executions=tool_executions,
        pending_actions=pending_actions,
    )
    app.dependency_overrides.clear()


def _name_catalog(*, fail: bool = False) -> KpiNameCatalog:
    async def professionals() -> list[Professional]:
        if fail:
            raise RuntimeError("dentalink down")
        return [Professional(id="p1", full_name="Dra. Ana", specialty_id="s1")]

    async def specialties() -> list[Specialty]:
        if fail:
            raise RuntimeError("dentalink down")
        return [Specialty(id="s1", name="Ortodoncia")]

    return KpiNameCatalog(professionals=professionals, specialties=specialties)


def _session_cookies(role: str, now: datetime | None = None) -> dict[str, str]:
    token, csrf = create_session_token(
        "admin-1", "tech1", role, _SECRET, _TTL, now=now or datetime.now(UTC)
    )
    return {"admin_session": token, "admin_csrf": csrf}


async def _get(path: str, cookies: dict[str, str] | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.get(path)


async def _post(
    path: str,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    json: dict[str, object] | None = None,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.post(path, headers=headers or {}, json=json)


# --- §75.3: authentication is required on every /admin route ------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/admin/api/conversations",
        "/admin/api/conversations/conv-1",
        "/admin/api/errors",
        "/admin/api/errors/err-1",
        "/admin/api/runs/run-1",
        "/admin/api/config",
        "/admin/api/me",
    ],
)
async def test_unauthenticated_request_is_rejected(path: str):
    response = await _get(path)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_expired_session_is_rejected():
    expired_now = datetime.now(UTC) - timedelta(hours=2)
    cookies = _session_cookies(READ_ONLY, now=expired_now)

    response = await _get("/admin/api/conversations", cookies=cookies)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_tampered_session_cookie_is_rejected():
    response = await _get("/admin/api/conversations", cookies={"admin_session": "garbage.garbage"})

    assert response.status_code == 401


# --- listing/detail views, any authenticated role ------------------------


@pytest.mark.asyncio
async def test_list_conversations_returns_a_summary_row(_override_admin_dependencies: _AdminFakes):
    fakes = _override_admin_dependencies
    await fakes.conversations.save(make_conversation(id_="conv-1", contact_id="contact-9"))
    await fakes.messages.save(make_message(id_="msg-1", conversation_id="conv-1", text="hola"))

    response = await _get("/admin/api/conversations", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["conversation_id"] == "conv-1"
    assert body[0]["patient_or_identifier"] == "contact-9"
    assert body[0]["last_message_text"] == "hola"


@pytest.mark.asyncio
async def test_get_conversation_detail_returns_404_for_a_missing_conversation():
    response = await _get("/admin/api/conversations/missing", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 404
    assert response.json()["detail"] == "Not found."


@pytest.mark.asyncio
async def test_get_conversation_detail_returns_messages_runs_and_errors(
    _override_admin_dependencies: _AdminFakes,
):
    fakes = _override_admin_dependencies
    await fakes.conversations.save(make_conversation(id_="conv-1"))
    await fakes.messages.save(make_message(id_="msg-1", conversation_id="conv-1"))
    await fakes.agent_runs.save(make_agent_run(id_="run-1", conversation_id="conv-1"))
    await fakes.errors.save(make_error_record(id_="err-1", conversation_id="conv-1"))

    response = await _get("/admin/api/conversations/conv-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["id"] == "conv-1"
    assert [m["id"] for m in body["messages"]] == ["msg-1"]
    assert [r["id"] for r in body["agent_runs"]] == ["run-1"]
    assert [e["id"] for e in body["errors"]] == ["err-1"]


@pytest.mark.asyncio
async def test_list_errors_returns_recent_errors(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))

    response = await _get("/admin/api/errors", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == ["err-1"]


@pytest.mark.asyncio
async def test_get_error_detail_returns_404_for_a_missing_error():
    response = await _get("/admin/api/errors/missing", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_error_detail_returns_the_error(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))

    response = await _get("/admin/api/errors/err-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    assert response.json()["id"] == "err-1"


@pytest.mark.asyncio
async def test_get_run_detail_returns_node_and_tool_executions(
    _override_admin_dependencies: _AdminFakes,
):
    fakes = _override_admin_dependencies
    await fakes.agent_runs.save(make_agent_run(id_="run-1"))
    await fakes.node_executions.save(
        make_node_execution(
            id_="ne-1",
            agent_run_id="run-1",
            input_summary="intent=appointment button=yes",
            output_summary="response_len=42",
        )
    )
    await fakes.tool_executions.save(make_tool_execution(id_="te-1", agent_run_id="run-1"))

    response = await _get("/admin/api/runs/run-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert body["agent_run"]["id"] == "run-1"
    assert [n["id"] for n in body["node_executions"]] == ["ne-1"]
    assert body["node_executions"][0]["input_summary"] == "intent=appointment button=yes"
    assert body["node_executions"][0]["output_summary"] == "response_len=42"
    assert [t["id"] for t in body["tool_executions"]] == ["te-1"]


@pytest.mark.asyncio
async def test_get_run_detail_returns_404_for_a_missing_run():
    response = await _get("/admin/api/runs/missing", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 404


# --- §75.3: READ_ONLY cannot mutate anything -----------------------------


@pytest.mark.asyncio
async def test_read_only_cannot_resolve_an_error(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(READ_ONLY)

    response = await _post(
        "/admin/api/errors/err-1/resolve",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 403


# --- §75.3: ADMIN_CLINIC cannot access restricted technical config -------


@pytest.mark.asyncio
async def test_admin_clinic_cannot_access_technical_config():
    response = await _get("/admin/api/config", cookies=_session_cookies(ADMIN_CLINIC))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_clinic_can_still_view_conversations(
    _override_admin_dependencies: _AdminFakes,
):
    response = await _get("/admin/api/conversations", cookies=_session_cookies(ADMIN_CLINIC))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_me_returns_the_sessions_username_and_role():
    # The panel's static pages (app/static/admin/app.js) call this on load
    # both as their auth check and to learn the role, which no client-side
    # JS can otherwise read off the HttpOnly session cookie.
    response = await _get("/admin/api/me", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    assert response.json() == {"username": "tech1", "role": READ_ONLY}


@pytest.mark.asyncio
async def test_admin_technical_can_access_technical_config():
    response = await _get("/admin/api/config", cookies=_session_cookies(ADMIN_TECHNICAL))

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "internal_eval_enabled",
        "groq_configured",
        "ycloud_configured",
        "dentalink_configured",
    }


# --- §75.3/§74.3: ADMIN_TECHNICAL + CSRF can resolve an error ------------


@pytest.mark.asyncio
async def test_admin_technical_resolves_an_error_with_a_valid_csrf_token(
    _override_admin_dependencies: _AdminFakes,
):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/errors/err-1/resolve",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 200
    assert response.json()["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_is_rejected_without_a_csrf_header(
    _override_admin_dependencies: _AdminFakes,
):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post("/admin/api/errors/err-1/resolve", cookies=cookies)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_is_rejected_with_a_wrong_csrf_token(
    _override_admin_dependencies: _AdminFakes,
):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/errors/err-1/resolve", cookies=cookies, headers={"x-csrf-token": "wrong-token"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_returns_404_for_a_missing_error():
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/errors/missing/resolve",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 404


# --- §75.3/§74.3: POST /admin/flows/create --------------------------------


class _StubYCloudClient:
    def __init__(self) -> None:
        self.create_flow_calls: list[dict[str, object]] = []
        self.preview_requests: list[str] = []
        self.send_flow_calls: list[dict[str, object]] = []

    async def create_flow(
        self, name: str, categories: list[str], flow_json: str, publish: bool = False
    ) -> str:
        self.create_flow_calls.append(
            {"name": name, "categories": categories, "flow_json": flow_json, "publish": publish}
        )
        return f"flow-{len(self.create_flow_calls)}"

    async def send_flow(self, to: str, body_text: str, **kwargs: object) -> str:
        self.send_flow_calls.append({"to": to, "body_text": body_text, **kwargs})
        return "wamid-test-1"

    async def get_flow_preview_url(self, flow_id: str) -> str:
        self.preview_requests.append(flow_id)
        return f"https://preview.example/{flow_id}"


@pytest.fixture
def _stub_ycloud_client() -> _StubYCloudClient:
    stub = _StubYCloudClient()
    app.dependency_overrides[get_ycloud_client] = lambda: stub
    yield stub
    del app.dependency_overrides[get_ycloud_client]


@pytest.fixture(autouse=True)
def _stub_agreements():
    """Never reach the real Dentalink from the flow routes."""
    gateway = make_agreement_gateway(
        agreements=[Agreement(id="1", name="OSDE"), Agreement(id="2", name="Galeno")]
    )
    app.dependency_overrides[get_agreement_gateway] = lambda: gateway
    yield gateway
    app.dependency_overrides.pop(get_agreement_gateway, None)


def _intake_dropdown_ids(flow_json: str) -> list[str]:
    form = json.loads(flow_json)["screens"][0]["layout"]["children"][0]
    new_patient_if = next(c for c in form["children"] if c["type"] == "If")
    dropdown = next(c for c in new_patient_if["then"] if c.get("name") == "obra_social")
    return [option["id"] for option in dropdown["data-source"]]


@pytest.mark.asyncio
async def test_admin_technical_creates_and_publishes_all_flows(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/create",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 200
    body = response.json()
    # The intake Flow is created first so a Meta rejection of it never leaves
    # duplicate legacy Flows behind.
    assert body == {
        "patient_intake_flow_id": "flow-1",
        "verification_flow_id": "flow-2",
        "registration_flow_id": "flow-3",
    }
    calls = _stub_ycloud_client.create_flow_calls
    assert len(calls) == 3
    assert all(call["publish"] is True for call in calls)
    intake_json = json.loads(str(calls[0]["flow_json"]))
    assert intake_json["screens"][0]["id"] == "DATOS_PACIENTE"
    assert _intake_dropdown_ids(str(calls[0]["flow_json"])) == ["particular", "OSDE", "Galeno"]
    # The logo is embedded as the form's first child.
    form = intake_json["screens"][0]["layout"]["children"][0]
    assert form["children"][0]["type"] == "Image"


@pytest.mark.asyncio
async def test_creating_flows_is_rejected_without_a_csrf_header(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post("/admin/api/flows/create", cookies=cookies)

    assert response.status_code == 403
    assert _stub_ycloud_client.create_flow_calls == []


@pytest.mark.asyncio
async def test_read_only_cannot_create_flows(_stub_ycloud_client: _StubYCloudClient):
    cookies = _session_cookies(READ_ONLY)

    response = await _post(
        "/admin/api/flows/create",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 403
    assert _stub_ycloud_client.create_flow_calls == []


# --- POST /admin/flows/intake-draft ---------------------------------------


@pytest.mark.asyncio
async def test_intake_draft_creates_only_an_unpublished_intake_flow_and_returns_its_preview(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/intake-draft",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "flow_id": "flow-1",
        "preview_url": "https://preview.example/flow-1",
    }
    (call,) = _stub_ycloud_client.create_flow_calls
    assert call["publish"] is False
    assert _intake_dropdown_ids(str(call["flow_json"])) == ["particular", "OSDE", "Galeno"]
    form = json.loads(str(call["flow_json"]))["screens"][0]["layout"]["children"][0]
    assert form["children"][0]["type"] == "Image"
    assert _stub_ycloud_client.preview_requests == ["flow-1"]


@pytest.mark.asyncio
async def test_intake_draft_uses_a_unique_flow_name_every_time(
    _stub_ycloud_client: _StubYCloudClient,
):
    # Meta rejects a Flow whose name already exists in the WhatsApp Business account,
    # so a second draft (or one next to an old published Flow) must not reuse a name.
    cookies = _session_cookies(ADMIN_TECHNICAL)
    headers = {"x-csrf-token": cookies["admin_csrf"]}

    await _post("/admin/api/flows/intake-draft", cookies=cookies, headers=headers)
    await asyncio.sleep(1.1)
    await _post("/admin/api/flows/intake-draft", cookies=cookies, headers=headers)

    names = [str(call["name"]) for call in _stub_ycloud_client.create_flow_calls]
    assert all(re.fullmatch(r"Datos de paciente \d{8}-\d{6}", name) for name in names)
    assert len(set(names)) == 2


@pytest.mark.asyncio
async def test_intake_draft_reports_a_ycloud_rejection_instead_of_a_bare_500(
    _stub_ycloud_client: _StubYCloudClient,
):
    async def _reject(*_args: object, **_kwargs: object) -> str:
        raise YCloudAPIError("YCloud API returned 400: Flow name is not unique", status_code=400)

    _stub_ycloud_client.create_flow = _reject  # type: ignore[method-assign]
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/intake-draft",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 502
    assert "Flow name is not unique" in response.json()["detail"]


@pytest.mark.asyncio
async def test_intake_draft_send_delivers_the_draft_flow_to_the_given_phone(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/intake-draft/send",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
        json={"flow_id": "flow-9", "to": "+5492254423359"},
    )

    assert response.status_code == 200
    assert response.json() == {"message_id": "wamid-test-1"}
    (call,) = _stub_ycloud_client.send_flow_calls
    assert call["to"] == "+5492254423359"
    assert call["flow_id"] == "flow-9"
    assert call["flow_screen_id"] == "DATOS_PACIENTE"
    # YCloud's Flow message schema has no `mode`: it must never be sent.
    assert "mode" not in call


@pytest.mark.asyncio
async def test_intake_draft_send_rejects_a_phone_that_is_not_e164(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/intake-draft/send",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
        json={"flow_id": "flow-9", "to": "2254423359"},
    )

    assert response.status_code == 422
    assert _stub_ycloud_client.send_flow_calls == []


@pytest.mark.asyncio
async def test_intake_draft_send_is_rejected_without_a_csrf_header_or_for_read_only(
    _stub_ycloud_client: _StubYCloudClient,
):
    technical = _session_cookies(ADMIN_TECHNICAL)
    no_csrf = await _post(
        "/admin/api/flows/intake-draft/send",
        cookies=technical,
        json={"flow_id": "flow-9", "to": "+5492254423359"},
    )
    read_only = _session_cookies(READ_ONLY)
    forbidden = await _post(
        "/admin/api/flows/intake-draft/send",
        cookies=read_only,
        headers={"x-csrf-token": read_only["admin_csrf"]},
        json={"flow_id": "flow-9", "to": "+5492254423359"},
    )

    assert no_csrf.status_code == 403
    assert forbidden.status_code == 403
    assert _stub_ycloud_client.send_flow_calls == []


@pytest.mark.asyncio
async def test_intake_draft_send_reports_a_ycloud_rejection_as_a_502(
    _stub_ycloud_client: _StubYCloudClient,
):
    async def _reject(*_args: object, **_kwargs: object) -> str:
        raise YCloudAPIError("YCloud API returned 400: outside the 24h window", status_code=400)

    _stub_ycloud_client.send_flow = _reject  # type: ignore[method-assign,assignment]
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/api/flows/intake-draft/send",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
        json={"flow_id": "flow-9", "to": "+5492254423359"},
    )

    assert response.status_code == 502
    assert "24h window" in response.json()["detail"]


@pytest.mark.asyncio
async def test_intake_draft_is_rejected_without_a_csrf_header(
    _stub_ycloud_client: _StubYCloudClient,
):
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post("/admin/api/flows/intake-draft", cookies=cookies)

    assert response.status_code == 403
    assert _stub_ycloud_client.create_flow_calls == []


@pytest.mark.asyncio
async def test_read_only_cannot_create_an_intake_draft(_stub_ycloud_client: _StubYCloudClient):
    cookies = _session_cookies(READ_ONLY)

    response = await _post(
        "/admin/api/flows/intake-draft",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 403
    assert _stub_ycloud_client.create_flow_calls == []


# --- GET /admin/api/graphs: static agent topology -------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY])
async def test_every_role_can_read_the_agent_graphs(role: str):
    response = await _get("/admin/api/graphs", cookies=_session_cookies(role))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=300"
    graphs = response.json()["graphs"]
    assert [g["id"] for g in graphs] == ["main", "appointment_decision", "first_visit_intake"]
    main = graphs[0]
    assert main["label"] == "Principal"
    assert {"id": "faq_topic", "label": "faq_topic", "kind": "node", "traced": True} in main[
        "nodes"
    ]
    assert {"from": "__start__", "to": "check_conversation_mode", "conditional": False} in main[
        "edges"
    ]


@pytest.mark.asyncio
async def test_anonymous_cannot_read_the_agent_graphs():
    response = await _get("/admin/api/graphs")

    assert response.status_code == 401


# --- GET /admin/api/graphs/state: per-node aggregates ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY])
async def test_every_role_can_read_the_graph_state(role: str):
    response = await _get("/admin/api/graphs/state", cookies=_session_cookies(role))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_anonymous_cannot_read_the_graph_state():
    response = await _get("/admin/api/graphs/state")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_graph_state_rejects_an_invalid_window():
    response = await _get("/admin/api/graphs/state?window=2h", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_graph_state_defaults_to_the_one_hour_window():
    response = await _get("/admin/api/graphs/state", cookies=_session_cookies(READ_ONLY))

    assert response.json()["window"] == "1h"


@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["15m", "1h", "24h"])
async def test_graph_state_echoes_the_requested_window(window: str):
    response = await _get(
        f"/admin/api/graphs/state?window={window}", cookies=_session_cookies(READ_ONLY)
    )

    assert response.json()["window"] == window


@pytest.mark.asyncio
async def test_graph_state_returns_the_aggregated_payload(
    _override_admin_dependencies: _AdminFakes,
):
    now = datetime.now(UTC)
    repo = _override_admin_dependencies.node_executions
    await repo.save(
        make_node_execution(
            id_="ne-ok",
            node_name="faq_topic",
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=5),
            duration_ms=100,
            agent_run_id="run-ok",
        )
    )
    await repo.save(
        make_node_execution(
            id_="ne-old",
            node_name="faq_topic",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3),
        )
    )
    await repo.save(
        make_node_execution(
            id_="ne-ghost",
            node_name="ghost_node",
            started_at=now - timedelta(minutes=1),
            finished_at=now - timedelta(minutes=1),
        )
    )

    body = (
        await _get("/admin/api/graphs/state?window=1h", cookies=_session_cookies(READ_ONLY))
    ).json()

    assert set(body) == {"generated_at", "window", "nodes", "unmapped", "truncated"}
    assert body["truncated"] is False
    assert body["unmapped"] == ["ghost_node"]
    node = body["nodes"]["faq_topic"]
    assert set(node) == {
        "count",
        "failed",
        "running",
        "last_status",
        "last_at",
        "avg_ms",
        "p50_ms",
        "last_error_id",
        "last_run_id",
    }
    assert node["count"] == 1
    assert node["failed"] == 0
    assert node["avg_ms"] == 100.0
    assert node["p50_ms"] == 100.0
    assert node["last_run_id"] == "run-ok"


# --- GET /admin/api/kpis: appointment KPIs (aggregates only) --------------

_KPI_KEYS = {
    "generated_at",
    "period",
    "previous_period",
    "totals",
    "per_day",
    "top_professionals",
    "top_specialties",
    "weekday",
    "hour",
    "weekday_hour",
    "without_slot",
    "evidence",
    "truncated",
    "previous_truncated",
}


async def _confirm(
    fakes: _AdminFakes,
    id_: str,
    at: datetime,
    action_type: str = "create_appointment",
    **payload: object,
) -> None:
    repo = fakes.pending_actions
    await repo.save(
        make_pending_action(
            id_=id_, action_type=action_type, payload=dict(payload), status="confirmed"
        )
    )
    repo.set_confirmed_at(id_, at)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY])
async def test_every_role_can_read_the_kpis(role: str):
    response = await _get("/admin/api/kpis", cookies=_session_cookies(role))

    assert response.status_code == 200
    assert set(response.json()) == _KPI_KEYS


@pytest.mark.asyncio
async def test_anonymous_cannot_read_the_kpis():
    response = await _get("/admin/api/kpis")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_kpis_are_never_cached():
    response = await _get("/admin/api/kpis", cookies=_session_cookies(READ_ONLY))

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_kpis_default_to_the_last_30_days_ending_today_in_the_clinic_timezone():
    today = datetime.now(ZoneInfo(Settings().clinic_timezone)).date()

    body = (await _get("/admin/api/kpis", cookies=_session_cookies(READ_ONLY))).json()

    assert body["period"]["date_to"] == today.isoformat()
    assert body["period"]["date_from"] == (today - timedelta(days=29)).isoformat()
    assert body["period"]["days"] == 30
    assert len(body["per_day"]) == 30


@pytest.mark.asyncio
async def test_kpis_default_from_is_29_days_before_an_explicit_to():
    body = (await _get("/admin/api/kpis?to=2026-09-30", cookies=_session_cookies(READ_ONLY))).json()

    assert body["period"]["date_from"] == "2026-09-01"
    assert body["period"]["date_to"] == "2026-09-30"


@pytest.mark.asyncio
async def test_an_empty_period_returns_zeros_not_an_error():
    body = (
        await _get(
            "/admin/api/kpis?from=2026-09-01&to=2026-09-30", cookies=_session_cookies(READ_ONLY)
        )
    ).json()

    zero = {"current": 0, "previous": 0, "change_pct": None}
    assert body["totals"] == {"taken": zero, "cancelled": zero, "rescheduled": zero}
    assert body["top_professionals"] == []
    assert body["top_specialties"] == []
    assert body["weekday"] == [0] * 7
    assert body["hour"] == [0] * 24
    assert body["weekday_hour"] == [[0] * 24 for _ in range(7)]
    assert body["without_slot"] == 0
    assert body["truncated"] is False
    assert all(day["taken"] == 0 and day["cancelled"] == 0 for day in body["per_day"])


@pytest.mark.asyncio
async def test_explicit_period_returns_the_aggregated_payload(
    _override_admin_dependencies: _AdminFakes,
):
    fakes = _override_admin_dependencies
    september = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
    await _confirm(
        fakes,
        "a1",
        september,
        professional_id="p1",
        specialty_id="s1",
        slot_start="2026-09-14T10:30:00",
        patient_name="Juan Perez",
    )
    await _confirm(fakes, "a2", september, professional_id="p1", specialty_id="s1")
    await _confirm(fakes, "c1", september, "cancel_appointment")
    await _confirm(fakes, "r1", september, "reschedule_appointment")
    await _confirm(fakes, "a-prev", datetime(2026, 8, 10, 15, 0, tzinfo=UTC))

    response = await _get(
        "/admin/api/kpis?from=2026-09-01&to=2026-09-30", cookies=_session_cookies(READ_ONLY)
    )

    body = response.json()
    assert body["totals"]["taken"] == {"current": 2, "previous": 1, "change_pct": 100.0}
    assert body["totals"]["cancelled"] == {"current": 1, "previous": 0, "change_pct": None}
    assert body["totals"]["rescheduled"] == {"current": 1, "previous": 0, "change_pct": None}
    assert body["period"]["date_from"] == "2026-09-01"
    assert body["period"]["date_to"] == "2026-09-30"
    assert body["previous_period"]["date_from"] == "2026-08-02"
    assert body["top_professionals"] == [{"id": "p1", "label": "Dra. Ana", "count": 2}]
    assert body["top_specialties"] == [{"id": "s1", "label": "Ortodoncia", "count": 2}]
    assert body["weekday"][0] == 1  # 2026-09-14 is a Monday
    assert body["hour"][10] == 1
    assert len(body["weekday_hour"]) == 7
    assert all(len(row) == 24 for row in body["weekday_hour"])
    assert body["weekday_hour"][0][10] == 1
    assert sum(sum(row) for row in body["weekday_hour"]) == 1
    assert body["without_slot"] == 1
    assert set(body["evidence"]) == {
        "taken_with",
        "taken_without",
        "cancelled_with",
        "cancelled_without",
        "truncated",
    }
    day = next(d for d in body["per_day"] if d["date"] == "2026-09-10")
    assert day == {"date": "2026-09-10", "taken": 2, "cancelled": 1}


@pytest.mark.asyncio
async def test_kpis_never_expose_patient_data(_override_admin_dependencies: _AdminFakes):
    await _confirm(
        _override_admin_dependencies,
        "a1",
        datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
        professional_id="p1",
        patient_name="Juan Perez",
        patient_id="patient-77",
    )

    response = await _get(
        "/admin/api/kpis?from=2026-09-01&to=2026-09-30", cookies=_session_cookies(READ_ONLY)
    )

    assert "Juan" not in response.text
    assert "patient-77" not in response.text


@pytest.mark.asyncio
async def test_labels_fall_back_to_ids_when_the_name_loader_fails(
    _override_admin_dependencies: _AdminFakes,
):
    app.dependency_overrides[get_kpi_name_catalog] = lambda: _name_catalog(fail=True)
    await _confirm(
        _override_admin_dependencies,
        "a1",
        datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
        professional_id="p1",
        specialty_id="s1",
    )

    response = await _get(
        "/admin/api/kpis?from=2026-09-01&to=2026-09-30", cookies=_session_cookies(READ_ONLY)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["top_professionals"] == [{"id": "p1", "label": "p1", "count": 1}]
    assert body["top_specialties"] == [{"id": "s1", "label": "s1", "count": 1}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "from=not-a-date",
        "from=2026-13-40&to=2026-09-30",
        "to=31/12/2026",
        "from=2026-09-30&to=2026-09-01",
        "from=2024-12-31&to=2026-01-01",
    ],
)
async def test_kpis_reject_invalid_ranges_with_422(query: str):
    response = await _get(f"/admin/api/kpis?{query}", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_kpis_range_errors_carry_a_clear_message():
    response = await _get(
        "/admin/api/kpis?from=2026-09-30&to=2026-09-01", cookies=_session_cookies(READ_ONLY)
    )

    assert isinstance(response.json()["detail"], str)
    assert "366" in response.json()["detail"]


@pytest.mark.asyncio
async def test_kpis_accept_a_range_of_exactly_366_days():
    response = await _get(
        "/admin/api/kpis?from=2025-01-01&to=2026-01-01", cookies=_session_cookies(READ_ONLY)
    )

    assert response.status_code == 200
    assert response.json()["period"]["days"] == 366
