"""Integration tests for `DebounceTracker` + `redis_lock` against a real Redis instance.

Skips when Redis is unreachable, mirroring `_postgres_reachable()` in
`tests/integration/conftest.py`.
"""

import asyncio
import socket
import time
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
    """Two concurrently-scheduled tasks contend for the same lock; only one may
    ever hold it at a time.

    This does NOT race on tight wall-clock margins (e.g. a ~100ms stagger vs. a
    ~200ms `blocking_timeout`). `redis.asyncio.lock.Lock`'s `blocking_timeout`
    only checks its deadline *between* polling attempts, not around each
    individual network call — against this project's real remote Redis
    instance, a single delayed `SET NX` can legitimately let the second task
    acquire the lock *after* the first released it, which is correct behavior
    but was previously misread by a strict "exactly one True" assertion as a
    mutual-exclusion violation, making the test flaky under normal network
    jitter.

    Instead, this proves mutual exclusion structurally: the second task only
    starts its attempt once it has confirmed (via an event, not a guessed
    stagger) that the first task already holds the lock, both tasks use a
    generous `blocking_timeout` so real latency never causes a spurious
    timeout, and the assertion checks that the two tasks' lock-held wall-clock
    intervals never overlap — which is what "only one holder at a time"
    actually means — rather than asserting a specific True/False shape.
    """
    name = "lock:conversation:integration-conv-3"
    hold_seconds = 1.0
    generous_blocking_timeout = 5.0
    first_task_acquired = asyncio.Event()
    held_intervals: list[tuple[float, float]] = []

    async def _hold_then_release() -> None:
        async with redis_lock(
            redis_client, name, timeout=10, blocking_timeout=generous_blocking_timeout
        ) as acquired:
            assert acquired is True  # nothing else holds this fresh lock yet
            start = time.monotonic()
            first_task_acquired.set()
            await asyncio.sleep(hold_seconds)
            held_intervals.append((start, time.monotonic()))

    async def _try_while_first_holds_it() -> None:
        # Wait for confirmation the first task actually holds the lock before
        # attempting — this guarantees genuine contention deterministically,
        # instead of hoping a wall-clock stagger wins the race.
        await asyncio.wait_for(first_task_acquired.wait(), timeout=generous_blocking_timeout)
        async with redis_lock(
            redis_client, name, timeout=10, blocking_timeout=generous_blocking_timeout
        ) as acquired:
            if acquired:
                start = time.monotonic()
                held_intervals.append((start, time.monotonic()))
            # else: correctly dropped without ever holding the lock — mutual
            # exclusion held without needing to acquire at all.

    await asyncio.gather(_hold_then_release(), _try_while_first_holds_it())

    # The first task always holds the lock at least once; the second either
    # times out (dropped) or acquires only once the first has released it.
    assert len(held_intervals) in (1, 2)
    ordered_intervals = sorted(held_intervals)
    for (_, previous_release), (next_acquire, _) in zip(
        ordered_intervals, ordered_intervals[1:], strict=False
    ):
        assert next_acquire >= previous_release
