from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.dependencies.auth import require_role
from app.domain.entities.admin_user import ROLES
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/admin", tags=["admin"])

_ANY_AUTHENTICATED_ROLE = tuple(ROLES)


@router.get("/openapi.json", include_in_schema=False)
async def admin_openapi_schema(
    request: Request,
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
) -> JSONResponse:
    """The public `/openapi.json` is disabled (see `app.main`) — this is the
    only way to fetch the schema, gated behind an admin session like every
    other `/admin/*` route. `request.app.openapi()` (not a module-level
    import of `app`) avoids a circular import with `app.main`.
    """
    return JSONResponse(request.app.openapi())


@router.get("/docs", include_in_schema=False)
async def admin_swagger_ui(
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/admin/openapi.json", title="Clinic AI Agent — API docs"
    )


@router.get("/redoc", include_in_schema=False)
async def admin_redoc(
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
) -> HTMLResponse:
    return get_redoc_html(openapi_url="/admin/openapi.json", title="Clinic AI Agent — API docs")
