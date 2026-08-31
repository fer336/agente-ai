from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.domain.entities.admin_audit_log_entry import (
    LOGIN_FAILURE,
    LOGIN_SUCCESS,
    AdminAuditLogEntry,
)
from app.domain.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.domain.repositories.admin_user_repository import AdminUserRepository
from app.infrastructure.auth.password_hashing import hash_password, verify_password
from app.infrastructure.auth.session_tokens import create_session_token

#: Hashed once, at import time, so a login attempt for a username that
#: doesn't exist still runs a real `scrypt` computation (against this fixed
#: hash) before failing — otherwise "no such user" would return measurably
#: faster than "wrong password", a timing side-channel that helps enumerate
#: valid usernames (PRD.md §74.3: "protección contra enumeración de
#: identificadores"). The dummy password itself is never checked against
#: anything real; only the computation's cost matters here.
_DUMMY_HASH = hash_password("not-a-real-password-used-only-for-timing")


@dataclass
class LoginResult:
    """Returned only on a successful login — see `AuthenticateAdminUseCase.login`."""

    admin_user_id: str
    role: str
    session_token: str
    csrf_token: str


class AuthenticateAdminUseCase:
    """Verifies admin-panel credentials and issues a session (PRD.md §74.3).

    Every attempt — success or failure — is audited (`AdminAuditLogRepository`),
    matching this same codebase's `ErrorService`-style "service wraps repos,
    exposes plain async methods" shape rather than a one-off route handler.
    """

    def __init__(
        self,
        admin_user_repository: AdminUserRepository,
        admin_audit_log_repository: AdminAuditLogRepository,
        session_secret: str,
        session_ttl_seconds: int,
    ) -> None:
        self._admin_user_repository = admin_user_repository
        self._admin_audit_log_repository = admin_audit_log_repository
        self._session_secret = session_secret
        self._session_ttl_seconds = session_ttl_seconds

    async def login(self, username: str, password: str, now: datetime) -> LoginResult | None:
        user = await self._admin_user_repository.get_by_username(username)

        if user is None or not user.is_active:
            verify_password(password, _DUMMY_HASH)  # timing parity, see `_DUMMY_HASH`
            await self._audit(admin_user_id=None, username=username, success=False, now=now)
            return None

        if not verify_password(password, user.password_hash):
            await self._audit(admin_user_id=user.id, username=username, success=False, now=now)
            return None

        session_token, csrf_token = create_session_token(
            user.id, user.username, user.role, self._session_secret, self._session_ttl_seconds, now
        )
        await self._audit(admin_user_id=user.id, username=username, success=True, now=now)
        return LoginResult(
            admin_user_id=user.id,
            role=user.role,
            session_token=session_token,
            csrf_token=csrf_token,
        )

    async def _audit(
        self, *, admin_user_id: str | None, username: str, success: bool, now: datetime
    ) -> None:
        await self._admin_audit_log_repository.save(
            AdminAuditLogEntry(
                id=str(uuid4()),
                admin_user_id=admin_user_id,
                username=username,
                action=LOGIN_SUCCESS if success else LOGIN_FAILURE,
                resource_type=None,
                resource_id=None,
                success=success,
                created_at=now,
            )
        )
