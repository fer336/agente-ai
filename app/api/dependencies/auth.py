import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status

from app.config.settings import Settings, get_settings
from app.infrastructure.auth.session_tokens import SessionPayload, verify_session_token

#: Cookie/header names shared by the login route (which sets them) and
#: these dependencies (which read them) — PRD.md §74.3's double-submit CSRF
#: pattern: `SESSION_COOKIE_NAME` is `HttpOnly`, `CSRF_COOKIE_NAME` is not
#: (the client must be able to read it to echo it back in `CSRF_HEADER_NAME`).
SESSION_COOKIE_NAME = "admin_session"
CSRF_COOKIE_NAME = "admin_csrf"
CSRF_HEADER_NAME = "x-csrf-token"

#: PRD.md §74.3: "respuestas genéricas en fallos de autenticación" — every
#: 401 this module raises uses this exact, non-specific message so a caller
#: can never distinguish "no cookie", "expired", or "tampered".
_AUTH_REQUIRED_DETAIL = "Authentication required."
_FORBIDDEN_DETAIL = "Forbidden."


def get_current_admin_session(
    request: Request, settings: Settings = Depends(get_settings)
) -> SessionPayload:
    """Resolves the caller's admin session from the `admin_session` cookie.

    Raises a generic 401 for every failure mode (missing cookie, expired,
    tampered, wrong secret) — see `verify_session_token`'s own docstring
    for why that collapse happens one level down already.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_REQUIRED_DETAIL)

    payload = verify_session_token(token, settings.admin_session_secret, now=datetime.now(UTC))
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_REQUIRED_DETAIL)

    return payload


def require_role(*roles: str) -> Callable[[SessionPayload], SessionPayload]:
    """Builds a dependency requiring an authenticated session in `roles`.

    Authorization is enforced here, in the backend, for every admin
    operation — PRD.md §74.3: "no será suficiente ocultar botones en el
    frontend."
    """

    def _dependency(
        session: SessionPayload = Depends(get_current_admin_session),
    ) -> SessionPayload:
        if session.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)
        return session

    return _dependency


def require_csrf(
    request: Request, session: SessionPayload = Depends(get_current_admin_session)
) -> SessionPayload:
    """Double-submit CSRF check for cookie-authenticated mutating routes
    (PRD.md §74.3/§75.3). Combine with `require_role(...)` in the route
    signature — FastAPI resolves `get_current_admin_session` once per
    request and shares it between both dependencies.
    """
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not header_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)

    actual_hash = hashlib.sha256(header_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_hash, session.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)

    return session
