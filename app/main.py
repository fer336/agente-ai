from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies.checkpointer import close_agent_checkpointer
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.health import router as health_router
from app.api.routes.internal_eval import router as internal_eval_router
from app.api.routes.webhook import router as webhook_router
from app.config.settings import get_settings


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


app = FastAPI(title="Clinic AI Agent", lifespan=lifespan)
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(internal_eval_router)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
