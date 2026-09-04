from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    """Builds the async SQLAlchemy engine for the given connection URL.

    `pool_pre_ping=True` issues a lightweight liveness check (`SELECT 1`)
    before handing out a pooled connection — without it, a connection the
    server has since dropped (restart, network blip, idle timeout) surfaces
    as `asyncpg.exceptions.ConnectionDoesNotExistError` on the NEXT request
    that happens to reuse it, crashing that request instead of transparently
    reconnecting.
    """
    return create_async_engine(database_url, echo=False, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Builds an async session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
