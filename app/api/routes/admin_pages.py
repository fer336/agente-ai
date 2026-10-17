from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

#: The panel has no build step and no hashed file names, so a browser that
#: heuristically caches `style.css` keeps showing an old (or unstyled) page
#: after a deploy. `no-cache` still lets the browser store the file, but forces
#: a revalidation (ETag / Last-Modified, answered with a cheap 304) on every use.
_REVALIDATE = {"Cache-Control": "no-cache"}


class RevalidatingStaticFiles(StaticFiles):
    """`StaticFiles` whose responses (200 and 304) always ask the browser to revalidate."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _page(name: str) -> FileResponse:
    return FileResponse(_STATIC_DIR / name, headers=_REVALIDATE)


@router.get("")
async def admin_root() -> RedirectResponse:
    return RedirectResponse(url="/admin/conversations")


@router.get("/login")
async def admin_login_page() -> FileResponse:
    return _page("login.html")


@router.get("/conversations")
async def admin_conversations_page() -> FileResponse:
    return _page("conversations.html")


@router.get("/conversations/{conversation_id}")
async def admin_conversation_detail_page(conversation_id: str) -> FileResponse:
    return _page("conversation-detail.html")


@router.get("/errors")
async def admin_errors_page() -> FileResponse:
    return _page("errors.html")


@router.get("/errors/{error_id}")
async def admin_error_detail_page(error_id: str) -> FileResponse:
    return _page("error-detail.html")


@router.get("/agent")
async def admin_agent_page() -> FileResponse:
    return _page("agent.html")


@router.get("/kpis")
async def admin_kpis_page() -> FileResponse:
    return _page("kpis.html")


@router.get("/runs/{agent_run_id}")
async def admin_run_detail_page(agent_run_id: str) -> FileResponse:
    return _page("run-detail.html")


@router.get("/llm-config")
async def admin_llm_config_page() -> FileResponse:
    return _page("llm-config.html")


@router.get("/agent-control")
async def admin_agent_control_page() -> FileResponse:
    return _page("agent-control.html")
