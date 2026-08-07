from functools import lru_cache

from redis.asyncio import Redis

from app.config.settings import get_settings
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.redis.debounce import DebounceTracker


@lru_cache
def get_shared_redis_client() -> Redis:
    """FastAPI dependency providing a long-lived, app-lifetime Redis client.

    Unlike `app.api.routes.health.get_redis_client` (a per-request async
    generator that closes the client after every `/ready` call),
    `IngestMessageUseCase`'s debounce/lock primitives keep using their
    Redis client from a background `asyncio.create_task` that continues
    well after the originating HTTP request/response cycle ends — it must
    not be closed mid-request the way the health-check client is.
    """
    return create_redis_client(get_settings().redis_url)


@lru_cache
def get_debounce_tracker() -> DebounceTracker:
    """FastAPI dependency providing the shared `DebounceTracker` singleton.

    Must be a singleton (not constructed fresh per call) for the same
    reason `IngestMessageUseCase` itself must be one — see that class's
    docstring: the debounce timers it tracks in Redis are meaningless if a
    fresh, unrelated `DebounceTracker` object were handed out per request
    (the object itself is stateless beyond its Redis client, but sharing it
    avoids constructing a new Redis-bound wrapper on every request).
    """
    return DebounceTracker(get_shared_redis_client(), get_settings().message_debounce_seconds)
