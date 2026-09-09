import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies.checkpointer import close_agent_checkpointer
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_docs import router as admin_docs_router
from app.api.routes.health import router as health_router
from app.api.routes.internal_eval import router as internal_eval_router
from app.api.routes.webhook import router as webhook_router
from app.config.settings import get_settings

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
    """Closes the LangGraph agent's Postgres checkpointer pool on shutdown.

    The pool itself is opened lazily, on first use, by
    `app.api.dependencies.checkpointer.get_agent_checkpointer` — not eagerly
    here at startup (same "no eager I/O" convention as the SQLAlchemy
    engine/session factory). A process that never runs a multi-turn flow
    needing the checkpointer never opens the pool, so this is a no-op then.
    """
    yield
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
app.include_router(admin_docs_router)
app.include_router(internal_eval_router)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
