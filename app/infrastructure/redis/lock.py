from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

LOCK_TIMEOUT_SECONDS = 30
LOCK_BLOCKING_TIMEOUT_SECONDS = 5


@asynccontextmanager
async def redis_lock(
    client: Redis,
    name: str,
    timeout: float = LOCK_TIMEOUT_SECONDS,
    blocking_timeout: float = LOCK_BLOCKING_TIMEOUT_SECONDS,
) -> AsyncIterator[bool]:
    """Acquire a per-conversation Redis lock; yields whether it was acquired.

    Drop-on-failure per the Etapa 4 design ADR: if `blocking_timeout` elapses
    without acquiring the lock, yields `False` instead of raising. Callers
    MUST check the yielded value and skip processing when it is `False` —
    this primitive never retries or requeues.
    """
    lock = client.lock(name, timeout=timeout, blocking_timeout=blocking_timeout)
    acquired = await lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            await lock.release()
