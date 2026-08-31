from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import (
    get_committing_error_query_service,
    get_conversation_query_service,
    get_error_query_service,
    get_run_query_service,
)
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.run_queries import RunQueryService
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.infrastructure.auth.session_tokens import create_session_token
from app.main import app
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_conversation_repository,
    make_error_repository,
    make_message_repository,
    make_node_execution_repository,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_conversation,
    make_error_record,
    make_message,
    make_node_execution,
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


@pytest.fixture(autouse=True)
def _override_admin_dependencies() -> _AdminFakes:
    app.dependency_overrides[get_settings] = _override_settings

    conversations = make_conversation_repository()
    messages = make_message_repository()
    agent_runs = make_agent_run_repository()
    errors = make_error_repository()
    node_executions = make_node_execution_repository()
    tool_executions = make_tool_execution_repository()

    conversation_service = ConversationQueryService(conversations, messages, agent_runs, errors)
    error_service = ErrorQueryService(errors)
    run_service = RunQueryService(agent_runs, node_executions, tool_executions)

    app.dependency_overrides[get_conversation_query_service] = lambda: conversation_service
    app.dependency_overrides[get_error_query_service] = lambda: error_service
    app.dependency_overrides[get_committing_error_query_service] = lambda: error_service
    app.dependency_overrides[get_run_query_service] = lambda: run_service

    yield _AdminFakes(
        conversations=conversations,
        messages=messages,
        agent_runs=agent_runs,
        errors=errors,
        node_executions=node_executions,
        tool_executions=tool_executions,
    )
    app.dependency_overrides.clear()


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
):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.post(path, headers=headers or {})


# --- §75.3: authentication is required on every /admin route ------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/admin/conversations",
        "/admin/conversations/conv-1",
        "/admin/errors",
        "/admin/errors/err-1",
        "/admin/runs/run-1",
        "/admin/config",
    ],
)
async def test_unauthenticated_request_is_rejected(path: str):
    response = await _get(path)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_expired_session_is_rejected():
    expired_now = datetime.now(UTC) - timedelta(hours=2)
    cookies = _session_cookies(READ_ONLY, now=expired_now)

    response = await _get("/admin/conversations", cookies=cookies)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_tampered_session_cookie_is_rejected():
    response = await _get("/admin/conversations", cookies={"admin_session": "garbage.garbage"})

    assert response.status_code == 401


# --- listing/detail views, any authenticated role ------------------------


@pytest.mark.asyncio
async def test_list_conversations_returns_a_summary_row(_override_admin_dependencies: _AdminFakes):
    fakes = _override_admin_dependencies
    await fakes.conversations.save(make_conversation(id_="conv-1", contact_id="contact-9"))
    await fakes.messages.save(make_message(id_="msg-1", conversation_id="conv-1", text="hola"))

    response = await _get("/admin/conversations", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["conversation_id"] == "conv-1"
    assert body[0]["patient_or_identifier"] == "contact-9"
    assert body[0]["last_message_text"] == "hola"


@pytest.mark.asyncio
async def test_get_conversation_detail_returns_404_for_a_missing_conversation():
    response = await _get("/admin/conversations/missing", cookies=_session_cookies(READ_ONLY))

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

    response = await _get("/admin/conversations/conv-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["id"] == "conv-1"
    assert [m["id"] for m in body["messages"]] == ["msg-1"]
    assert [r["id"] for r in body["agent_runs"]] == ["run-1"]
    assert [e["id"] for e in body["errors"]] == ["err-1"]


@pytest.mark.asyncio
async def test_list_errors_returns_recent_errors(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))

    response = await _get("/admin/errors", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == ["err-1"]


@pytest.mark.asyncio
async def test_get_error_detail_returns_404_for_a_missing_error():
    response = await _get("/admin/errors/missing", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_error_detail_returns_the_error(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))

    response = await _get("/admin/errors/err-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    assert response.json()["id"] == "err-1"


@pytest.mark.asyncio
async def test_get_run_detail_returns_node_and_tool_executions(
    _override_admin_dependencies: _AdminFakes,
):
    fakes = _override_admin_dependencies
    await fakes.agent_runs.save(make_agent_run(id_="run-1"))
    await fakes.node_executions.save(make_node_execution(id_="ne-1", agent_run_id="run-1"))
    await fakes.tool_executions.save(make_tool_execution(id_="te-1", agent_run_id="run-1"))

    response = await _get("/admin/runs/run-1", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 200
    body = response.json()
    assert body["agent_run"]["id"] == "run-1"
    assert [n["id"] for n in body["node_executions"]] == ["ne-1"]
    assert [t["id"] for t in body["tool_executions"]] == ["te-1"]


@pytest.mark.asyncio
async def test_get_run_detail_returns_404_for_a_missing_run():
    response = await _get("/admin/runs/missing", cookies=_session_cookies(READ_ONLY))

    assert response.status_code == 404


# --- §75.3: READ_ONLY cannot mutate anything -----------------------------


@pytest.mark.asyncio
async def test_read_only_cannot_resolve_an_error(_override_admin_dependencies: _AdminFakes):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(READ_ONLY)

    response = await _post(
        "/admin/errors/err-1/resolve",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 403


# --- §75.3: ADMIN_CLINIC cannot access restricted technical config -------


@pytest.mark.asyncio
async def test_admin_clinic_cannot_access_technical_config():
    response = await _get("/admin/config", cookies=_session_cookies(ADMIN_CLINIC))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_clinic_can_still_view_conversations(
    _override_admin_dependencies: _AdminFakes,
):
    response = await _get("/admin/conversations", cookies=_session_cookies(ADMIN_CLINIC))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_technical_can_access_technical_config():
    response = await _get("/admin/config", cookies=_session_cookies(ADMIN_TECHNICAL))

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
        "/admin/errors/err-1/resolve",
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

    response = await _post("/admin/errors/err-1/resolve", cookies=cookies)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_is_rejected_with_a_wrong_csrf_token(
    _override_admin_dependencies: _AdminFakes,
):
    await _override_admin_dependencies.errors.save(make_error_record(id_="err-1"))
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/errors/err-1/resolve", cookies=cookies, headers={"x-csrf-token": "wrong-token"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_returns_404_for_a_missing_error():
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _post(
        "/admin/errors/missing/resolve",
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 404
