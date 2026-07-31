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
