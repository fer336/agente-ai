from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

#: `app/static/admin/` — plain HTML/CSS/JS, no build step, no templating
#: engine. Auth is entirely client-side (each page's own <script> calls
#: `ADMIN.requireAuth()`, which redirects to /admin/login on a 401) —
#: these routes never touch a session cookie themselves, so serving the
#: bare HTML shell needs no dependency here. PRD.md §44's own three
#: routes (`/admin/conversations`, `/admin/errors`, `/admin/runs/{id}`)
#: are pages a human visits in a browser; the JSON data layer they call
#: lives under `/admin/api/*` (see `app.api.routes.admin`) specifically
#: so it doesn't collide with these exact paths.
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "admin"

router = APIRouter(prefix="/admin", tags=["admin-pages"], include_in_schema=False)


@router.get("")
async def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/admin/conversations")


@router.get("/login")
async def admin_login_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "login.html")


@router.get("/conversations")
async def admin_conversations_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "conversations.html")


@router.get("/conversations/{conversation_id}")
async def admin_conversation_detail_page(conversation_id: str) -> FileResponse:
    return FileResponse(_STATIC_DIR / "conversation-detail.html")


@router.get("/errors")
async def admin_errors_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "errors.html")


@router.get("/errors/{error_id}")
async def admin_error_detail_page(error_id: str) -> FileResponse:
    return FileResponse(_STATIC_DIR / "error-detail.html")


@router.get("/runs/{agent_run_id}")
async def admin_run_detail_page(agent_run_id: str) -> FileResponse:
    return FileResponse(_STATIC_DIR / "run-detail.html")
