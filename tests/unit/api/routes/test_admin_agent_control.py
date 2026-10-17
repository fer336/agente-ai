from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import get_committing_admin_audit_log_repository
from app.api.dependencies.config import get_runtime_config_service
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_audit_log_entry import (
    AGENT_CONTACT_FILTER_UPDATED,
    AGENT_PAUSED,
    AGENT_RESUMED,
)
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)
from app.main import app
from tests.fixtures.gateways import make_runtime_config_service

_SECRET = "test-admin-secret"
_TTL = 3600
_URL = "/admin/api/agent-control"


def _override_settings() -> Settings:
    return Settings(admin_session_secret=_SECRET, admin_session_ttl_seconds=_TTL, _env_file=None)


@pytest.fixture(autouse=True)
def _deps():
    app.dependency_overrides[get_settings] = _override_settings
    service = make_runtime_config_service(
        model="fake-model",
        temperature=0.2,
        classify_intent_prompt="classify this",
        extract_information_prompt="extract {required_fields}",
        generate_response_prompt="respond to {intent} with {collected_data}",
    )
    audit = FakeAdminAuditLogRepository()
    app.dependency_overrides[get_runtime_config_service] = lambda: service
    app.dependency_overrides[get_committing_admin_audit_log_repository] = lambda: audit
    yield service, audit
    app.dependency_overrides.clear()


def _cookies(role: str, username: str = "tech1") -> dict[str, str]:
    token, csrf = create_session_token(
        "admin-1", username, role, _SECRET, _TTL, now=datetime.now(UTC)
    )
    return {"admin_session": token, "admin_csrf": csrf}


async def _get(cookies: dict[str, str] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.get(_URL)


async def _put(body: dict[str, object], cookies: dict[str, str] | None = None, csrf: bool = True):
    headers = {"x-csrf-token": cookies["admin_csrf"]} if csrf and cookies else {}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.put(_URL, json=body, headers=headers)


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent_paused": False,
        "contact_filter_mode": "off",
        "contact_filter_phones": [],
    }
    return {**base, **overrides}


# --- GET -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_get_is_rejected():
    assert (await _get()).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY])
async def test_every_role_can_read_the_state(role: str):
    response = await _get(_cookies(role))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "agent_paused",
        "paused_by",
        "paused_at",
        "contact_filter_mode",
        "contact_filter_phones",
        "updated_at",
    }
    assert body["agent_paused"] is False
    assert body["contact_filter_mode"] == "off"
    assert body["contact_filter_phones"] == []


# --- PUT: auth -------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_put_is_rejected():
    assert (await _put(_body())).status_code == 401


@pytest.mark.asyncio
async def test_read_only_cannot_update():
    assert (await _put(_body(), _cookies(READ_ONLY))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC])
async def test_admins_can_update(role: str):
    response = await _put(_body(agent_paused=True), _cookies(role))

    assert response.status_code == 200
    assert response.json()["agent_paused"] is True


@pytest.mark.asyncio
async def test_update_requires_the_csrf_header():
    assert (await _put(_body(), _cookies(ADMIN_TECHNICAL), csrf=False)).status_code == 403


# --- PUT: validation -------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_mode_is_rejected():
    response = await _put(_body(contact_filter_mode="block"), _cookies(ADMIN_CLINIC))

    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", ["1234567", "1" * 16, "abc"])
async def test_phone_with_wrong_digit_count_is_rejected(phone: str):
    response = await _put(
        _body(contact_filter_mode="deny", contact_filter_phones=[phone]), _cookies(ADMIN_CLINIC)
    )

    assert response.status_code == 400
    assert "dígitos" in response.json()["detail"]


@pytest.mark.asyncio
async def test_allow_mode_with_an_empty_list_is_rejected():
    response = await _put(
        _body(contact_filter_mode="allow", contact_filter_phones=[" ", ""]),
        _cookies(ADMIN_CLINIC),
    )

    assert response.status_code == 400
    assert "nadie" in response.json()["detail"]


@pytest.mark.asyncio
async def test_more_than_500_phones_are_rejected():
    phones = [f"54911{n:08d}" for n in range(501)]

    response = await _put(
        _body(contact_filter_mode="deny", contact_filter_phones=phones), _cookies(ADMIN_CLINIC)
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_phones_are_normalized_deduplicated_and_blanks_dropped():
    response = await _put(
        _body(
            contact_filter_mode="deny",
            contact_filter_phones=["+54 9 11-1234-5678", "", "5491112345678", "5491100000000"],
        ),
        _cookies(ADMIN_CLINIC),
    )

    assert response.status_code == 200
    assert response.json()["contact_filter_phones"] == ["5491112345678", "5491100000000"]


@pytest.mark.asyncio
async def test_off_mode_may_keep_a_stored_list():
    response = await _put(
        _body(contact_filter_mode="off", contact_filter_phones=["5491112345678"]),
        _cookies(ADMIN_CLINIC),
    )

    assert response.status_code == 200


# --- PUT: state ------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preserves_the_other_config_fields(_deps):
    service, _ = _deps
    before = await service.get_config()

    await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC))

    after = await service.get_config()
    assert after.model == before.model
    assert after.temperature == before.temperature
    assert after.debounce_seconds == before.debounce_seconds
    assert after.classify_intent_prompt == before.classify_intent_prompt
    assert after.extract_information_prompt == before.extract_information_prompt
    assert after.generate_response_prompt == before.generate_response_prompt


@pytest.mark.asyncio
async def test_pausing_records_who_and_when_and_resuming_clears_them():
    paused = await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC, "ana"))

    assert paused.json()["paused_by"] == "ana"
    assert paused.json()["paused_at"] is not None

    resumed = await _put(_body(agent_paused=False), _cookies(ADMIN_TECHNICAL, "tech1"))

    assert resumed.json()["paused_by"] is None
    assert resumed.json()["paused_at"] is None


@pytest.mark.asyncio
async def test_staying_paused_keeps_the_original_pauser(_deps):
    first = await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC, "ana"))

    second = await _put(
        _body(
            agent_paused=True, contact_filter_mode="deny", contact_filter_phones=["5491112345678"]
        ),
        _cookies(ADMIN_TECHNICAL, "tech1"),
    )

    assert second.json()["paused_by"] == "ana"
    assert second.json()["paused_at"] == first.json()["paused_at"]


@pytest.mark.asyncio
async def test_the_inbound_gate_sees_the_change_through_the_service(_deps):
    service, _ = _deps
    assert await service.agent_may_respond("5491112345678") is True

    await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC))
    assert await service.agent_may_respond("5491112345678") is False

    await _put(
        _body(contact_filter_mode="deny", contact_filter_phones=["+54 9 11 1234 5678"]),
        _cookies(ADMIN_CLINIC),
    )
    assert await service.agent_may_respond("5491112345678") is False
    assert await service.agent_may_respond("5491199999999") is True


# --- PUT: audit ------------------------------------------------------------


@pytest.mark.asyncio
async def test_pausing_writes_one_paused_entry_without_phones(_deps):
    _, audit = _deps

    await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC, "ana"))

    entries = audit.all()
    assert [e.action for e in entries] == [AGENT_PAUSED]
    assert entries[0].username == "ana"
    assert entries[0].success is True


@pytest.mark.asyncio
async def test_resuming_writes_a_resumed_entry(_deps):
    _, audit = _deps
    await _put(_body(agent_paused=True), _cookies(ADMIN_CLINIC))

    await _put(_body(agent_paused=False), _cookies(ADMIN_CLINIC))

    assert [e.action for e in audit.all()] == [AGENT_PAUSED, AGENT_RESUMED]


@pytest.mark.asyncio
async def test_filter_change_writes_a_filter_entry_and_never_the_phone(_deps):
    _, audit = _deps

    await _put(
        _body(contact_filter_mode="deny", contact_filter_phones=["5491112345678"]),
        _cookies(ADMIN_CLINIC),
    )

    entries = audit.all()
    assert [e.action for e in entries] == [AGENT_CONTACT_FILTER_UPDATED]
    assert "5491112345678" not in repr(entries[0])


@pytest.mark.asyncio
async def test_both_kinds_of_change_write_both_entries(_deps):
    _, audit = _deps

    await _put(
        _body(
            agent_paused=True, contact_filter_mode="deny", contact_filter_phones=["5491112345678"]
        ),
        _cookies(ADMIN_CLINIC),
    )

    assert {e.action for e in audit.all()} == {AGENT_PAUSED, AGENT_CONTACT_FILTER_UPDATED}


@pytest.mark.asyncio
async def test_a_no_op_save_writes_no_audit_entry(_deps):
    _, audit = _deps

    response = await _put(_body(), _cookies(ADMIN_CLINIC))

    assert response.status_code == 200
    assert audit.all() == []


@pytest.mark.asyncio
async def test_a_rejected_update_writes_no_audit_entry_and_changes_nothing(_deps):
    service, audit = _deps

    await _put(_body(agent_paused=True, contact_filter_mode="allow"), _cookies(ADMIN_CLINIC))

    assert audit.all() == []
    assert (await service.get_config()).agent_paused is False
