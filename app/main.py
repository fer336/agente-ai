<<<<<<< Updated upstream
=======
import asyncio
>>>>>>> Stashed changes
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.api.dependencies.checkpointer import close_agent_checkpointer, get_agent_checkpointer
from app.api.dependencies.gateways import get_messaging_gateway
from app.api.dependencies.repositories import (
    open_sqlalchemy_agent_repositories,
    open_sqlalchemy_proposal_repositories,
)
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_auth import router as admin_auth_router
from app.api.routes.admin_docs import router as admin_docs_router
from app.api.routes.health import router as health_router
from app.api.routes.internal_eval import router as internal_eval_router
from app.api.routes.webhook import router as webhook_router
from app.application.messages.send_reply import SendReplyUseCase
from app.config.settings import get_settings
from app.workers.follow_up_worker import run_follow_up_tick

logger = logging.getLogger(__name__)


async def _run_follow_up_tick_once() -> None:
    settings = get_settings()
    checkpointer = await get_agent_checkpointer()
    async with (
        open_sqlalchemy_agent_repositories() as agent_repositories,
        open_sqlalchemy_proposal_repositories() as proposal_repositories,
    ):
        await run_follow_up_tick(
            scheduled_action_repository=proposal_repositories.scheduled_actions,
            message_repository=agent_repositories.messages,
            conversation_repository=agent_repositories.conversations,
            contact_repository=agent_repositories.contacts,
            send_reply=SendReplyUseCase(get_messaging_gateway()),
            checkpointer=checkpointer,
            now=datetime.now(UTC),
            limit=settings.follow_up_worker_batch_limit,
            reset_delay_seconds=settings.appointment_follow_up_reset_delay_seconds,
        )


async def _run_follow_up_loop() -> None:
    """This session's own brief: turns `run_follow_up_tick` (a "one poll
    tick" function, same convention as `app.workers.audio_tasks`/
    `incident_tasks`/`memory_tasks`) into an actual periodic loop.

    Same `asyncio.create_task` pattern `IngestMessageUseCase` already uses
    for its own debounce timers — no new dependency (no APScheduler/ARQ/
    cron) — but more robust than that debounce: the real state
    (`ScheduledAction` rows) lives in Postgres, so a process restart only
    restarts THIS loop, it never loses the work a tick was about to do.
    A single tick raising never kills the loop — logged and retried on the
    next interval, same "one bad row/turn never breaks the sweep" posture
    `check_incident_recovery`/`process_pending_audio_jobs` already follow.
    """
    settings = get_settings()
    while True:
        try:
            await _run_follow_up_tick_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("follow_up_worker.tick_failed")
        await asyncio.sleep(settings.follow_up_worker_interval_seconds)

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
    """Starts the inactivity follow-up loop and closes the LangGraph
    agent's Postgres checkpointer pool on shutdown.

    The checkpointer pool itself is opened lazily, on first use, by
    `app.api.dependencies.checkpointer.get_agent_checkpointer` — not eagerly
    here at startup (same "no eager I/O" convention as the SQLAlchemy
    engine/session factory). A process that never runs a multi-turn flow
    needing the checkpointer never opens the pool on its own, but the
    follow-up loop below calls it on its very first tick regardless.
    """
    follow_up_task = asyncio.create_task(_run_follow_up_loop())
    yield
    follow_up_task.cancel()
    try:
        await follow_up_task
    except asyncio.CancelledError:
        pass
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
