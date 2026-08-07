from redis.asyncio import Redis

from app.api.dependencies.redis import get_debounce_tracker, get_shared_redis_client
from app.infrastructure.redis.debounce import DebounceTracker


def test_get_shared_redis_client_returns_a_redis_client():
    client = get_shared_redis_client()

    assert isinstance(client, Redis)


def test_get_shared_redis_client_returns_the_same_cached_instance_across_calls():
    first = get_shared_redis_client()
    second = get_shared_redis_client()

    assert first is second


def test_get_debounce_tracker_returns_a_debounce_tracker():
    tracker = get_debounce_tracker()

    assert isinstance(tracker, DebounceTracker)


def test_get_debounce_tracker_returns_the_same_cached_instance_across_calls():
    first = get_debounce_tracker()
    second = get_debounce_tracker()

    assert first is second
