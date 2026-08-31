from datetime import UTC, datetime

import pytest

from app.application.admin.authenticate_admin import AuthenticateAdminUseCase
from app.domain.entities.admin_audit_log_entry import LOGIN_FAILURE, LOGIN_SUCCESS
from app.domain.entities.admin_user import ADMIN_TECHNICAL, AdminUser
from app.infrastructure.auth.password_hashing import hash_password
from app.infrastructure.auth.session_tokens import verify_session_token
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)
from app.infrastructure.database.fake_admin_user_repository import FakeAdminUserRepository

_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
_SECRET = "test-secret"


def _use_case(
    users: FakeAdminUserRepository, audit: FakeAdminAuditLogRepository
) -> AuthenticateAdminUseCase:
    return AuthenticateAdminUseCase(users, audit, session_secret=_SECRET, session_ttl_seconds=3600)


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_credentials_and_issues_a_valid_session():
    users = FakeAdminUserRepository()
    await users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=_NOW,
        )
    )
    audit = FakeAdminAuditLogRepository()
    use_case = _use_case(users, audit)

    result = await use_case.login("tech1", "correct-password", now=_NOW)

    assert result is not None
    assert result.admin_user_id == "admin-1"
    assert result.role == ADMIN_TECHNICAL
    payload = verify_session_token(result.session_token, _SECRET, now=_NOW)
    assert payload is not None
    assert payload.admin_user_id == "admin-1"


@pytest.mark.asyncio
async def test_login_succeeds_audits_a_login_success_entry():
    users = FakeAdminUserRepository()
    await users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=_NOW,
        )
    )
    audit = FakeAdminAuditLogRepository()
    use_case = _use_case(users, audit)

    await use_case.login("tech1", "correct-password", now=_NOW)

    entries = audit.all()
    assert len(entries) == 1
    assert entries[0].action == LOGIN_SUCCESS
    assert entries[0].admin_user_id == "admin-1"
    assert entries[0].success is True


@pytest.mark.asyncio
async def test_login_fails_with_wrong_password_and_audits_a_failure():
    users = FakeAdminUserRepository()
    await users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=True,
            created_at=_NOW,
        )
    )
    audit = FakeAdminAuditLogRepository()
    use_case = _use_case(users, audit)

    result = await use_case.login("tech1", "wrong-password", now=_NOW)

    assert result is None
    entries = audit.all()
    assert len(entries) == 1
    assert entries[0].action == LOGIN_FAILURE
    assert entries[0].admin_user_id == "admin-1"


@pytest.mark.asyncio
async def test_login_fails_for_an_unknown_username_with_the_same_generic_outcome():
    users = FakeAdminUserRepository()
    audit = FakeAdminAuditLogRepository()
    use_case = _use_case(users, audit)

    result = await use_case.login("no-such-user", "anything", now=_NOW)

    assert result is None
    entries = audit.all()
    assert len(entries) == 1
    assert entries[0].action == LOGIN_FAILURE
    assert entries[0].admin_user_id is None
    assert entries[0].username == "no-such-user"


@pytest.mark.asyncio
async def test_login_fails_for_a_deactivated_account_even_with_the_correct_password():
    users = FakeAdminUserRepository()
    await users.save(
        AdminUser(
            id="admin-1",
            username="tech1",
            password_hash=hash_password("correct-password"),
            role=ADMIN_TECHNICAL,
            is_active=False,
            created_at=_NOW,
        )
    )
    audit = FakeAdminAuditLogRepository()
    use_case = _use_case(users, audit)

    result = await use_case.login("tech1", "correct-password", now=_NOW)

    assert result is None
