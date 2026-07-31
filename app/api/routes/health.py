from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_db_session
from app.config.settings import get_settings

router = APIRouter()


async def get_redis_client() -> AsyncGenerator[Any, None]:
    """FastAPI dependency yielding a Redis client.

    The `redis` package import is deferred to call time (not module import
    time) so importing this module — and therefore `app.main` and the
    `/health` endpoint — never requires `redis` to be installed. Only
    `/ready` actually invokes this dependency.
    """
    from app.infrastructure.redis.client import create_redis_client

    client = create_redis_client(get_settings().redis_url)
    try:
        yield client
    finally:
        await client.aclose()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — no dependency checks, just proves the process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    redis_client: Any = Depends(get_redis_client),
) -> dict[str, str]:
    """Readiness probe — checks Postgres and Redis connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ready"}
