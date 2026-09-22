import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.dependencies.checkpointer import close_agent_checkpointer, get_agent_checkpointer
from app.api.dependencies.gateways import get_messaging_gateway, get_mirror_to_chatwoot_use_case
from app.api.dependencies.repositories import (
    open_sqlalchemy_follow_up_worker_repositories,
    open_sqlalchemy_sent_message_repository,
)
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_docs import router as admin_docs_router
from app.api.routes.admin_llm_config import router as admin_llm_config_router
from app.api.routes.admin_pages import router as admin_pages_router
from app.api.routes.health import router as health_router
from app.api.routes.internal_eval import router as internal_eval_router
from app.api.routes.webhook import router as webhook_router
from app.application.messages.send_reply import SendReplyUseCase
from app.config.settings import get_settings
from app.workers.follow_up_worker import run_follow_up_loop

#: The app's own `logger.info`/`logger.warning` calls (webhook handling,
#: YCloud tag sync, error reporting, ...) are otherwise silently dropped in
#: production: uvicorn only configures ITS OWN loggers (`uvicorn`,
#: `uvicorn.access`, `uvicorn.error`), never the root logger our modules'
#: `logging.getLogger(__name__)` calls attach to. Without this, only
#: uvicorn's own access log line (method/path/status) reaches stdout —
#: every application-level log line (e.g. `webhook.tag_mode_synced`,
#: `ycloud_handoff.contact_not_found_by_phone`) never does, even though the
#: code path that logs it did run. Must be configured before any module-level
#: `logging.getLogger(__name__)` call actually logs, so this runs at import
#: time, before `app = FastAPI(...)` below.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Starts the inactivity follow-up poll loop as a background task, and
    closes the LangGraph agent's Postgres checkpointer pool on shutdown.

    The checkpointer pool itself is opened lazily, on first use, by
    `app.api.dependencies.checkpointer.get_agent_checkpointer` — not eagerly
    here at startup (same "no eager I/O" convention as the SQLAlchemy
    engine/session factory). A process that never runs a multi-turn flow
    needing the checkpointer never opens the pool, so closing it is a no-op
    then.

    The follow-up loop (`app.workers.follow_up_worker.run_follow_up_loop`)
    was previously never started anywhere — its own docstrings claimed this
    function was what turned it into a real periodic process, but nothing
    here actually did, so a stuck trámite never got its "¿seguís ahí?"
    nudge or silent-free auto-reset. Cancelled (not merely abandoned) on
    shutdown so its current tick's `asyncio.sleep` doesn't outlive the
    process.
    """
    settings = get_settings()
    follow_up_task = asyncio.create_task(
        run_follow_up_loop(
            open_sqlalchemy_follow_up_worker_repositories,
            get_agent_checkpointer,
            SendReplyUseCase(
                get_messaging_gateway(),
                open_sqlalchemy_sent_message_repository,
                mirror_to_chatwoot=get_mirror_to_chatwoot_use_case(),
            ),
            interval_seconds=settings.follow_up_worker_interval_seconds,
            batch_limit=settings.follow_up_worker_batch_limit,
            reset_delay_seconds=settings.appointment_follow_up_reset_delay_seconds,
        )
    )
    yield
    follow_up_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await follow_up_task
    await close_agent_checkpointer()


#: The default `/docs`, `/redoc`, `/openapi.json` are public and unauthenticated
#: by default — disabled here so the API schema (including the `/admin/*`
#: surface) isn't world-readable. `admin_docs_router` re-exposes equivalents
#: under `/admin/docs`, `/admin/redoc`, `/admin/openapi.json`, gated behind
#: the same admin session auth as the rest of the panel.
app = FastAPI(
    title="Clinic AI Agent",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(admin_llm_config_router)
app.include_router(admin_docs_router)
app.include_router(admin_pages_router)
app.include_router(internal_eval_router)
#: The admin panel's own CSS/JS (app/static/admin/{style.css,app.js}) —
#: plain static files, no auth needed to fetch them (they carry no data,
#: only markup/behavior; the real data calls from app.js are what the
#: session cookie/CSRF check actually guards).
app.mount(
    "/admin/static",
    StaticFiles(directory=Path(__file__).resolve().parent / "static" / "admin"),
    name="admin-static",
)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
