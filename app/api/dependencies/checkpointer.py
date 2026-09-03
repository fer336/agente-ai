from typing import TYPE_CHECKING

from app.agent.graph import create_checkpointer, create_postgres_checkpointer_pool
from app.config.settings import get_settings

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.agent.graph import PostgresCheckpointerPool

_pool: "PostgresCheckpointerPool | None" = None
_saver: "AsyncPostgresSaver | None" = None


async def get_agent_checkpointer() -> "AsyncPostgresSaver":
    """Lazily opens the Postgres checkpointer pool on first call, caches it after.

    Mirrors `app.api.dependencies.db._get_session_factory`'s lazy-singleton
    convention (no eager connection at import/startup time), adapted for an
    async open step (`AsyncConnectionPool.open()`) that cannot happen
    inside a sync `@lru_cache`d function — see `LangGraphAgentInvoker`'s
    own docstring for why it takes a `checkpointer_provider` callable
    (this function) rather than a `checkpointer` instance built once at
    DI-wiring time. Needed starting with the appointment-creation flow
    (multi-turn: identify -> select -> confirm), which relies on the
    checkpointer to carry `collected_data`/`pending_action_id` across
    separate inbound messages — the single-turn flows (agreement/handoff/
    fallback) never needed it.
    """
    global _pool, _saver
    if _saver is None:
        settings = get_settings()
        _pool = create_postgres_checkpointer_pool(settings.checkpointer_database_url)
        await _pool.open()
        _saver = await create_checkpointer(_pool)
    return _saver


async def close_agent_checkpointer() -> None:
    """Closes the checkpointer pool, if one was ever opened.

    Called from the FastAPI lifespan on shutdown (`app.main`). A no-op if
    `get_agent_checkpointer` was never called (e.g. a process that only
    ever ran single-turn flows).
    """
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = None
    _saver = None
