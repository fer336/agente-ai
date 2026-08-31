from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.api.dependencies.admin import get_authenticate_admin_use_case
from app.api.dependencies.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    get_current_admin_session,
)
from app.application.admin.authenticate_admin import AuthenticateAdminUseCase
from app.config.settings import Settings, get_settings
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/admin", tags=["admin"])

#: PRD.md §74.3: "respuestas genéricas en fallos de autenticación" — a wrong
#: password and an unknown username both produce this exact message.
_INVALID_CREDENTIALS_DETAIL = "Invalid credentials."


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    use_case: AuthenticateAdminUseCase = Depends(get_authenticate_admin_use_case),
) -> LoginResponse:
    """PRD.md §74.3's admin-panel login. Sets two cookies on success:
    `admin_session` (`HttpOnly`, carries the signed session) and
    `admin_csrf` (readable by the client's own JS, echoed back as the
    `X-CSRF-Token` header on mutating requests — see
    `app.api.dependencies.auth.require_csrf`).
    """
    result = await use_case.login(body.username, body.password, now=datetime.now(UTC))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        )

    response.set_cookie(
        SESSION_COOKIE_NAME,
        result.session_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.admin_session_ttl_seconds,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        result.csrf_token,
        httponly=False,
        secure=True,
        samesite="strict",
        max_age=settings.admin_session_ttl_seconds,
    )
    return LoginResponse(role=result.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    _session: SessionPayload = Depends(get_current_admin_session),
) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
