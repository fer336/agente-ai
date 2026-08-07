"""Integration tests for `DebounceTracker` + `redis_lock` against a real Redis instance.

Skips when Redis is unreachable, mirroring `_postgres_reachable()` in
`tests/integration/conftest.py`.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator

import pytest
from redis.asyncio import Redis

from app.config.settings import get_settings
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.redis.debounce import DebounceTracker
from app.infrastructure.redis.lock import redis_lock


def _redis_reachable() -> bool:
    settings = get_settings()
    try:
        with socket.create_connection((settings.redis_host, settings.redis_port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    if not _redis_reachable():
        pytest.skip("Redis not reachable for debounce/lock integration test")

    settings = get_settings()
    client = create_redis_client(settings.redis_url)
    yield client

    await client.flushdb()
    await client.aclose()


@pytest.mark.asyncio
async def test_ttl_refresh_extends_the_debounce_window(redis_client: Redis) -> None:
    tracker = DebounceTracker(redis_client, debounce_seconds=1)

    first_token = await tracker.touch("integration-conv-1")
    await asyncio.sleep(0.5)
    second_token = await tracker.touch("integration-conv-1")
    await asyncio.sleep(0.7)  # 1.2s since first touch, 0.7s since second — still within TTL

    assert await tracker.is_stale("integration-conv-1", first_token) is True
    assert await tracker.is_stale("integration-conv-1", second_token) is False


@pytest.mark.asyncio
async def test_key_expires_after_the_debounce_window_elapses(redis_client: Redis) -> None:
    tracker = DebounceTracker(redis_client, debounce_seconds=1)

    token = await tracker.touch("integration-conv-2")
    await asyncio.sleep(1.2)

    assert await tracker.is_stale("integration-conv-2", token) is False  # expired, not superseded


@pytest.mark.asyncio
async def test_lock_contention_across_two_concurrent_tasks(redis_client: Redis) -> None:
    name = "lock:conversation:integration-conv-3"
    results: list[bool] = []

    async def _hold_then_release() -> None:
        async with redis_lock(redis_client, name, timeout=5, blocking_timeout=0.2) as acquired:
            results.append(acquired)
            if acquired:
                await asyncio.sleep(0.5)

    async def _try_shortly_after() -> None:
        await asyncio.sleep(0.1)
        async with redis_lock(redis_client, name, timeout=5, blocking_timeout=0.2) as acquired:
            results.append(acquired)

    await asyncio.gather(_hold_then_release(), _try_shortly_after())

    assert results.count(True) == 1
    assert results.count(False) == 1
