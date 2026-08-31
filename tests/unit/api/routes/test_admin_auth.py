from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import get_authenticate_admin_use_case
from app.application.admin.authenticate_admin import AuthenticateAdminUseCase
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_audit_log_entry import LOGIN_FAILURE, LOGIN_SUCCESS
from app.domain.entities.admin_user import ADMIN_TECHNICAL, AdminUser
from app.infrastructure.auth.password_hashing import hash_password
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)
from app.infrastructure.database.fake_admin_user_repository import FakeAdminUserRepository
from app.main import app

_SECRET = "test-admin-secret"
_TTL = 3600


def _override_settings() -> Settings:
    return Settings(admin_session_secret=_SECRET, admin_session_ttl_seconds=_TTL, _env_file=None)


@dataclass
class _AuthFakes:
    admin_users: FakeAdminUserRepository
    admin_audit_log: FakeAdminAuditLogRepository


@pytest.fixture(autouse=True)
def _override_admin_auth() -> _AuthFakes:
    app.dependency_overrides[get_settings] = _override_settings

    admin_users = FakeAdminUserRepository()
    admin_audit_log = FakeAdminAuditLogRepository()
    use_case = AuthenticateAdminUseCase(
        admin_users, admin_audit_log, session_secret=_SECRET, session_ttl_seconds=_TTL
    )
    app.dependency_overrides[get_authenticate_admin_use_case] = lambda: use_case

    yield _AuthFakes(admin_users=admin_users, admin_audit_log=admin_audit_log)
    app.dependency_overrides.clear()


async def _post_login(username: str, password: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/admin/login", json={"username": username, "password": password})


@pytest.mark.asyncio
async def test_login_succeeds_and_sets_session_and_csrf_cookies(_override_admin_auth: _AuthFakes):
    await _override_admin_auth.admin_users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )

    response = await _post_login("tech1", "correct-password")

    assert response.status_code == 200
    assert response.json() == {"role": ADMIN_TECHNICAL}
    assert "admin_session" in response.cookies
    assert "admin_csrf" in response.cookies


@pytest.mark.asyncio
async def test_login_fails_with_a_generic_message_for_wrong_password(
    _override_admin_auth: _AuthFakes,
):
    await _override_admin_auth.admin_users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )

    response = await _post_login("tech1", "wrong-password")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


@pytest.mark.asyncio
async def test_login_fails_with_the_same_generic_message_for_an_unknown_username(
    _override_admin_auth: _AuthFakes,
):
    response = await _post_login("no-such-user", "anything")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


@pytest.mark.asyncio
async def test_login_success_and_failure_are_both_audited(_override_admin_auth: _AuthFakes):
    await _override_admin_auth.admin_users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )

    await _post_login("tech1", "wrong-password")
    await _post_login("tech1", "correct-password")

    actions = [entry.action for entry in _override_admin_auth.admin_audit_log.all()]
    assert actions == [LOGIN_FAILURE, LOGIN_SUCCESS]


@pytest.mark.asyncio
async def test_logout_requires_an_authenticated_session():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/logout")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookies_for_an_authenticated_session():
    session_token, csrf_token = create_session_token(
        "admin-1", "tech1", ADMIN_TECHNICAL, _SECRET, _TTL, now=datetime.now(UTC)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"admin_session": session_token, "admin_csrf": csrf_token},
    ) as client:
        response = await client.post("/admin/logout")

    assert response.status_code == 204
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        header.startswith("admin_session=") and "Max-Age=0" in header
        for header in set_cookie_headers
    )
