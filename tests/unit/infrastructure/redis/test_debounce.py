import pytest

from app.infrastructure.redis.debounce import DebounceTracker
from tests.fixtures.fake_redis import InMemoryFakeRedis


@pytest.mark.asyncio
async def test_touch_sets_a_debounce_key_with_ttl():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    token = await tracker.touch("conv-1")

    assert await redis.get("debounce:conversation:conv-1") == token.encode()


@pytest.mark.asyncio
async def test_retouch_resets_the_key_with_a_new_token():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    first_token = await tracker.touch("conv-1")
    second_token = await tracker.touch("conv-1")

    assert first_token != second_token
    assert await redis.get("debounce:conversation:conv-1") == second_token.encode()


@pytest.mark.asyncio
async def test_is_stale_is_true_for_a_token_superseded_by_a_later_touch():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    old_token = await tracker.touch("conv-1")
    await tracker.touch("conv-1")

    assert await tracker.is_stale("conv-1", old_token) is True


@pytest.mark.asyncio
async def test_is_stale_is_false_for_the_latest_token():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    token = await tracker.touch("conv-1")

    assert await tracker.is_stale("conv-1", token) is False


@pytest.mark.asyncio
async def test_is_stale_is_false_when_the_key_has_naturally_expired():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    token = await tracker.touch("conv-1")
    await redis.delete("debounce:conversation:conv-1")

    assert await tracker.is_stale("conv-1", token) is False


@pytest.mark.asyncio
async def test_touch_for_one_conversation_does_not_affect_another():
    redis = InMemoryFakeRedis()
    tracker = DebounceTracker(redis, debounce_seconds=6)

    await tracker.touch("conv-1")

    assert await redis.get("debounce:conversation:conv-2") is None
