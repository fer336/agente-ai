from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import create_app

HEALTH_PATHS = {"/health", "/ready"}
BOT_PATHS = {
    "/webhooks/ycloud/{secret}",
    "/webhooks/chatwoot/{secret}",
    "/internal/eval/chat",
    "/public",
}
ADMIN_PATHS = {
    "/admin/login",
    "/admin/logout",
    "/admin/api/me",
    "/admin/api/conversations",
    "/admin/api/conversations/{conversation_id}",
    "/admin/api/conversations/{conversation_id}/reset",
    "/admin/api/errors",
    "/admin/api/errors/{error_id}",
    "/admin/api/errors/{error_id}/resolve",
    "/admin/api/runs/{agent_run_id}",
    "/admin/api/graphs",
    "/admin/api/graphs/state",
    "/admin/api/kpis",
    "/admin/api/config",
    "/admin/api/flows/create",
    "/admin/api/flows/intake-draft",
    "/admin/api/flows/intake-draft/send",
    "/admin/api/llm-config",
    "/admin/openapi.json",
    "/admin/docs",
    "/admin/redoc",
    "/admin",
    "/admin/conversations",
    "/admin/conversations/{conversation_id}",
    "/admin/errors",
    "/admin/errors/{error_id}",
    "/admin/runs/{agent_run_id}",
    "/admin/agent",
    "/admin/kpis",
    "/admin/llm-config",
    "/admin/static",
}


def _paths(app: FastAPI) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            paths.update(r.path for r in original.routes)
        else:
            paths.add(route.path)  # type: ignore[attr-defined]
    return paths


def test_all_role_serves_exactly_the_pre_split_route_set():
    assert _paths(create_app("all")) == HEALTH_PATHS | BOT_PATHS | ADMIN_PATHS


def test_module_level_app_is_the_default_all_role():
    assert _paths(main_module.app) == HEALTH_PATHS | BOT_PATHS | ADMIN_PATHS


def test_bot_role_has_no_admin_routes():
    assert _paths(create_app("bot")) == HEALTH_PATHS | BOT_PATHS


def test_admin_role_has_no_bot_routes():
    assert _paths(create_app("admin")) == HEALTH_PATHS | ADMIN_PATHS


def test_docs_stay_disabled_for_every_role():
    for role in ("bot", "admin", "all"):
        app = create_app(role)
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        create_app("worker")


def test_admin_app_returns_404_for_bot_surfaces():
    client = TestClient(create_app("admin"))
    assert client.post("/webhooks/ycloud/x", json={}).status_code == 404
    assert client.post("/webhooks/chatwoot/x", json={}).status_code == 404
    assert client.post("/internal/eval/chat", json={}).status_code == 404
    assert client.get("/public/anything.png").status_code == 404
    assert client.get("/admin/static/style.css").status_code == 200


def test_bot_app_returns_404_for_admin_surfaces():
    client = TestClient(create_app("bot"))
    assert client.post("/admin/login", json={}).status_code == 404
    assert client.get("/admin/login").status_code == 404
    assert client.get("/admin/static/style.css").status_code == 404
    assert client.get("/health").status_code == 200


@pytest.fixture
def workers(monkeypatch):
    follow_up = Mock(return_value=_noop())
    reminder = Mock(return_value=None)
    close = AsyncMock()
    monkeypatch.setattr(main_module, "run_follow_up_loop", follow_up)
    monkeypatch.setattr(main_module, "start_appointment_reminder_worker", reminder)
    monkeypatch.setattr(main_module, "close_agent_checkpointer", close)
    monkeypatch.setattr(main_module, "get_messaging_gateway", Mock())
    monkeypatch.setattr(main_module, "get_mirror_to_chatwoot_use_case", Mock())
    return follow_up, reminder, close


async def _noop() -> None:
    return None


@pytest.mark.parametrize("role", ["bot", "all"])
def test_bot_and_all_roles_start_the_workers(workers, role):
    follow_up, reminder, close = workers
    with TestClient(create_app(role)):
        pass
    follow_up.assert_called_once()
    reminder.assert_called_once()
    close.assert_awaited_once()


def test_admin_role_starts_no_workers_but_still_closes_the_checkpointer(workers):
    follow_up, reminder, close = workers
    with TestClient(create_app("admin")):
        pass
    follow_up.assert_not_called()
    reminder.assert_not_called()
    close.assert_awaited_once()
