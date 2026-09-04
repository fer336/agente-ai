from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.infrastructure.database.session import create_engine, create_session_factory


def test_create_engine_returns_async_engine_bound_to_the_given_url():
    engine = create_engine("postgresql+asyncpg://user:pass@localhost:5432/db")

    assert isinstance(engine, AsyncEngine)
    assert engine.url.username == "user"
    assert engine.url.database == "db"


def test_create_engine_binds_a_different_url_correctly():
    engine = create_engine("postgresql+asyncpg://other:pw@otherhost:5433/otherdb")

    assert engine.url.host == "otherhost"
    assert engine.url.port == 5433
    assert engine.url.database == "otherdb"


def test_create_engine_enables_pool_pre_ping():
    # Regression: without this, a connection the server dropped (restart,
    # idle timeout) surfaces as ConnectionDoesNotExistError on next use
    # instead of transparently reconnecting.
    engine = create_engine("postgresql+asyncpg://user:pass@localhost:5432/db")

    assert engine.pool._pre_ping is True


def test_create_session_factory_returns_sessionmaker_bound_to_the_engine():
    engine = create_engine("postgresql+asyncpg://user:pass@localhost:5432/db")

    factory = create_session_factory(engine)

    assert isinstance(factory, async_sessionmaker)
    session = factory()
    assert isinstance(session, AsyncSession)
    assert session.bind is engine
