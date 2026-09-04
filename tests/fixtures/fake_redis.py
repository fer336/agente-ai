"""Hand-rolled in-memory fake Redis client for unit tests.

No `fakeredis` dependency exists in this project (checked `pyproject.toml`)
and none is added — this fake implements only the small surface
`DebounceTracker` and `redis_lock()` need (SET with PX/EX/GET/DELETE, plus a
minimal `lock()` factory), matching the existing `Fake*` convention
(`FakeWhatsAppGateway`, `FakeContactRepository`, ...) rather than pulling in
a new dependency. Values are returned as `bytes`, mirroring the real
`redis.asyncio.Redis` client (`decode_responses` defaults to `False` in
`create_redis_client`).
"""

import asyncio
import time


class InMemoryFakeLock:
    """Minimal async lock mimicking `redis.asyncio.lock.Lock`'s acquire/release contract."""

    def __init__(
        self, store: "InMemoryFakeRedis", name: str, blocking_timeout: float | None
    ) -> None:
        self._store = store
        self._name = name
        self._blocking_timeout = blocking_timeout
        self._held = False

    async def acquire(self) -> bool:
        deadline = (
            None if self._blocking_timeout is None else time.monotonic() + self._blocking_timeout
        )
        while True:
            if self._name not in self._store.held_locks():
                self._store._locks.add(self._name)
                self._held = True
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.01)

    async def release(self) -> None:
        if self._held:
            self._store._locks.discard(self._name)
            self._held = False


class InMemoryFakeRedis:
    """In-memory fake implementing the small Redis surface debounce/lock need."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[bytes, float | None]] = {}
        self._locks: set[str] = set()

    async def set(
        self, name: str, value: str, px: int | None = None, ex: int | None = None
    ) -> bool:
        ttl_seconds = ex if px is None else px / 1000
        expires_at = None if ttl_seconds is None else time.monotonic() + ttl_seconds
        self._values[name] = (value.encode(), expires_at)
        return True

    async def get(self, name: str) -> bytes | None:
        entry = self._values.get(name)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._values[name]
            return None
        return value

    async def delete(self, name: str) -> None:
        self._values.pop(name, None)

    async def incr(self, name: str) -> int:
        current = await self.get(name)
        new_value = (int(current) if current is not None else 0) + 1
        existing = self._values.get(name)
        expires_at = existing[1] if existing is not None else None
        self._values[name] = (str(new_value).encode(), expires_at)
        return new_value

    async def expire(self, name: str, seconds: int) -> bool:
        existing = self._values.get(name)
        if existing is None:
            return False
        value, _ = existing
        self._values[name] = (value, time.monotonic() + seconds)
        return True

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        blocking_timeout: float | None = None,
    ) -> InMemoryFakeLock:
        return InMemoryFakeLock(self, name, blocking_timeout)

    def held_locks(self) -> frozenset[str]:
        return frozenset(self._locks)
