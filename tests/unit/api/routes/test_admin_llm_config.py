from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import get_committing_admin_audit_log_repository
from app.api.dependencies.config import get_runtime_config_service
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_audit_log_entry import LLM_CONFIG_UPDATED
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)
from app.main import app
from tests.fixtures.gateways import make_runtime_config_service

_SECRET = "test-admin-secret"
_TTL = 3600


def _override_settings() -> Settings:
    return Settings(admin_session_secret=_SECRET, admin_session_ttl_seconds=_TTL, _env_file=None)


@pytest.fixture(autouse=True)
def _override_llm_config_dependencies():
    app.dependency_overrides[get_settings] = _override_settings

    runtime_config_service = make_runtime_config_service(
        model="fake-model",
        temperature=0.2,
        classify_intent_prompt="classify this",
        extract_information_prompt="extract {required_fields}",
        generate_response_prompt="respond to {intent} with {collected_data}",
    )
    audit_log_repository = FakeAdminAuditLogRepository()

    app.dependency_overrides[get_runtime_config_service] = lambda: runtime_config_service
    app.dependency_overrides[get_committing_admin_audit_log_repository] = (
        lambda: audit_log_repository
    )

    yield runtime_config_service, audit_log_repository
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


async def _put(
    path: str,
    json: dict[str, object],
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.put(path, json=json, headers=headers or {})


_VALID_UPDATE = {
    "model": "gpt-new",
    "temperature": 0.7,
    "classify_intent_prompt": "classify carefully",
    "extract_information_prompt": "extract {required_fields} please",
    "generate_response_prompt": "answer {intent} using {collected_data}",
}


# --- GET /admin/api/llm-config -------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_get_is_rejected():
    response = await _get("/admin/api/llm-config")

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [READ_ONLY, ADMIN_CLINIC])
async def test_non_technical_roles_cannot_read_llm_config(role: str):
    response = await _get("/admin/api/llm-config", cookies=_session_cookies(role))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_technical_reads_the_llm_config():
    response = await _get("/admin/api/llm-config", cookies=_session_cookies(ADMIN_TECHNICAL))

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "model",
        "temperature",
        "classify_intent_prompt",
        "extract_information_prompt",
        "generate_response_prompt",
        "updated_at",
        "updated_by",
    }
    assert body["model"] == "fake-model"
    assert body["temperature"] == 0.2


# --- PUT /admin/api/llm-config --------------------------------------------


@pytest.mark.asyncio
async def test_non_technical_role_cannot_update_llm_config():
    cookies = _session_cookies(READ_ONLY)

    response = await _put(
        "/admin/api/llm-config",
        json=_VALID_UPDATE,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_is_rejected_without_a_csrf_header():
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _put("/admin/api/llm-config", json=_VALID_UPDATE, cookies=cookies)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_is_rejected_with_a_wrong_csrf_token():
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _put(
        "/admin/api/llm-config",
        json=_VALID_UPDATE,
        cookies=cookies,
        headers={"x-csrf-token": "wrong-token"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_technical_updates_the_llm_config_with_a_valid_csrf_token():
    cookies = _session_cookies(ADMIN_TECHNICAL)

    response = await _put(
        "/admin/api/llm-config",
        json=_VALID_UPDATE,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-new"
    assert body["temperature"] == 0.7
    assert body["updated_by"] == "tech1"

    follow_up = await _get("/admin/api/llm-config", cookies=cookies)
    assert follow_up.json()["model"] == "gpt-new"


@pytest.mark.asyncio
async def test_update_preserves_debounce_seconds_from_the_existing_config(
    _override_llm_config_dependencies,
):
    runtime_config_service, _ = _override_llm_config_dependencies
    cookies = _session_cookies(ADMIN_TECHNICAL)

    await _put(
        "/admin/api/llm-config",
        json=_VALID_UPDATE,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    config = await runtime_config_service.get_config()
    assert config.debounce_seconds == 6


@pytest.mark.asyncio
async def test_update_rejects_a_prompt_missing_the_required_fields_placeholder():
    cookies = _session_cookies(ADMIN_TECHNICAL)
    body = {**_VALID_UPDATE, "extract_information_prompt": "extract stuff, no placeholder"}

    response = await _put(
        "/admin/api/llm-config",
        json=body,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 400
    assert "required_fields" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_rejects_a_response_prompt_missing_the_intent_placeholder():
    cookies = _session_cookies(ADMIN_TECHNICAL)
    body = {**_VALID_UPDATE, "generate_response_prompt": "answer using {collected_data} only"}

    response = await _put(
        "/admin/api/llm-config",
        json=body,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 400
    assert "intent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_rejects_a_response_prompt_missing_the_collected_data_placeholder():
    cookies = _session_cookies(ADMIN_TECHNICAL)
    body = {**_VALID_UPDATE, "generate_response_prompt": "answer {intent} only"}

    response = await _put(
        "/admin/api/llm-config",
        json=body,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 400
    assert "collected_data" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_rejects_a_temperature_out_of_range():
    cookies = _session_cookies(ADMIN_TECHNICAL)
    body = {**_VALID_UPDATE, "temperature": 3.5}

    response = await _put(
        "/admin/api/llm-config",
        json=body,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_a_successful_update_writes_one_audit_log_entry(
    _override_llm_config_dependencies,
):
    _, audit_log_repository = _override_llm_config_dependencies
    cookies = _session_cookies(ADMIN_TECHNICAL)

    await _put(
        "/admin/api/llm-config",
        json=_VALID_UPDATE,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    entries = audit_log_repository.all()
    assert len(entries) == 1
    assert entries[0].action == LLM_CONFIG_UPDATED
    assert entries[0].username == "tech1"
    assert entries[0].resource_type == "runtime_agent_config"
    assert entries[0].success is True


@pytest.mark.asyncio
async def test_a_rejected_update_writes_no_audit_log_entry(
    _override_llm_config_dependencies,
):
    _, audit_log_repository = _override_llm_config_dependencies
    cookies = _session_cookies(ADMIN_TECHNICAL)
    body = {**_VALID_UPDATE, "generate_response_prompt": "no placeholders here"}

    await _put(
        "/admin/api/llm-config",
        json=body,
        cookies=cookies,
        headers={"x-csrf-token": cookies["admin_csrf"]},
    )

    assert audit_log_repository.all() == []
