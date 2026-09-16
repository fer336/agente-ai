"""Integration tests for `/health` and `/ready` (design Testing Strategy:
"Integration | `/health`, `/ready` | `AsyncClient` + `dependency_overrides`
(fastapi-templates pattern)").

Both dependencies (`get_db_session`, `get_redis_client`) are overridden with
fakes so this suite runs without a real Postgres/Redis and without the
`redis` package installed.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ProgrammingError

from app.api.dependencies.db import get_db_session
from app.api.routes.health import get_redis_client
from app.main import app


class _FakeSession:
    async def execute(self, *args: object, **kwargs: object) -> None:
        return None


class _FailingSession:
    async def execute(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("postgres unreachable")


class _ReachableButMissingSchemaSession:
    """Connectivity works (`SELECT 1` succeeds) but the real schema is
    missing — regression for the live incident where `alembic_version`
    claimed head while every application table (including `messages`) was
    actually absent, and `/ready` kept reporting healthy through 6+
    releases because it only ever ran `SELECT 1`."""

    async def execute(self, statement: object, *args: object, **kwargs: object) -> None:
        if "messages" in str(statement):
            raise ProgrammingError("SELECT 1 FROM messages", {}, Exception("UndefinedTable"))
        return None


class _FakeRedis:
    async def ping(self) -> bool:
        return True


class _FailingRedis:
    async def ping(self) -> bool:
        raise ConnectionError("redis unreachable")


async def _override_db_session_ok() -> AsyncGenerator[_FakeSession, None]:
    yield _FakeSession()


async def _override_db_session_failing() -> AsyncGenerator[_FailingSession, None]:
    yield _FailingSession()


async def _override_db_session_missing_schema() -> (
    AsyncGenerator[_ReachableButMissingSchemaSession, None]
):
    yield _ReachableButMissingSchemaSession()


async def _override_redis_ok() -> AsyncGenerator[_FakeRedis, None]:
    yield _FakeRedis()


async def _override_redis_failing() -> AsyncGenerator[_FailingRedis, None]:
    yield _FailingRedis()


@pytest.mark.asyncio
async def test_health_returns_200_without_checking_any_dependency():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_200_when_postgres_and_redis_are_reachable():
    app.dependency_overrides[get_db_session] = _override_db_session_ok
    app.dependency_overrides[get_redis_client] = _override_redis_ok
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_ready_returns_503_when_postgres_is_unreachable():
    app.dependency_overrides[get_db_session] = _override_db_session_failing
    app.dependency_overrides[get_redis_client] = _override_redis_ok
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ready_returns_503_when_connected_but_the_schema_is_missing():
    # Regression: `alembic_version` can claim migrations are at head while
    # the tables they were supposed to create don't actually exist — a
    # bare `SELECT 1` stays healthy in that state, so this must probe a
    # real table too.
    app.dependency_overrides[get_db_session] = _override_db_session_missing_schema
    app.dependency_overrides[get_redis_client] = _override_redis_ok
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ready_returns_503_when_redis_is_unreachable():
    app.dependency_overrides[get_db_session] = _override_db_session_ok
    app.dependency_overrides[get_redis_client] = _override_redis_failing
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
