from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.infrastructure.database.session import create_engine, create_session_factory


@lru_cache
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Builds a single session factory bound to a single engine, reused across requests."""
    engine = create_engine(get_settings().database_url)
    return create_session_factory(engine)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an `AsyncSession` for the request lifetime."""
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield session


async def get_committing_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Like `get_db_session`, but commits once the route handler returns
    successfully.

    For routes whose write must survive past this one request/response
    cycle (an admin-panel login's audit entry, an error being marked
    resolved) — plain `get_db_session` alone would leave those writes
    flushed-but-uncommitted, discarded when the session closes (same
    pitfall `open_sqlalchemy_proposal_repositories`/
    `open_sqlalchemy_trace_repositories` document for the process-singleton
    use cases). If the route raises, this generator's `commit()` is never
    reached — FastAPI propagates the exception through the `yield` point
    before resuming here, so a failed request correctly persists nothing.
    """
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield session
        await session.commit()
