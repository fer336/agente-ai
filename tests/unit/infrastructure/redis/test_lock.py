import pytest

from app.infrastructure.redis.lock import redis_lock
from tests.fixtures.fake_redis import InMemoryFakeRedis


@pytest.mark.asyncio
async def test_lock_is_acquired_and_released_when_free():
    redis = InMemoryFakeRedis()

    async with redis_lock(
        redis, "lock:conversation:conv-1", timeout=30, blocking_timeout=5
    ) as acquired:
        assert acquired is True
        assert "lock:conversation:conv-1" in redis.held_locks()

    assert "lock:conversation:conv-1" not in redis.held_locks()


@pytest.mark.asyncio
async def test_lock_reports_not_acquired_when_blocking_timeout_elapses():
    redis = InMemoryFakeRedis()
    holder = redis.lock("lock:conversation:conv-1", blocking_timeout=None)
    await holder.acquire()

    async with redis_lock(
        redis, "lock:conversation:conv-1", timeout=30, blocking_timeout=0.05
    ) as acquired:
        assert acquired is False

    await holder.release()


@pytest.mark.asyncio
async def test_lock_failure_does_not_raise():
    redis = InMemoryFakeRedis()
    holder = redis.lock("lock:conversation:conv-1", blocking_timeout=None)
    await holder.acquire()

    try:
        async with redis_lock(
            redis, "lock:conversation:conv-1", timeout=30, blocking_timeout=0.05
        ):
            pass
    except Exception as exc:  # noqa: BLE001 — asserting NO exception is the point of this test
        pytest.fail(f"redis_lock raised on acquisition failure instead of dropping: {exc}")
    finally:
        await holder.release()


@pytest.mark.asyncio
async def test_concurrent_conversations_use_independent_locks():
    redis = InMemoryFakeRedis()

    async with redis_lock(
        redis, "lock:conversation:conv-1", timeout=30, blocking_timeout=5
    ) as first:
        async with redis_lock(
            redis, "lock:conversation:conv-2", timeout=30, blocking_timeout=5
        ) as second:
            assert first is True
            assert second is True
