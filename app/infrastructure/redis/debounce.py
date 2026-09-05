import uuid

from redis.asyncio import Redis

_KEY_PREFIX = "debounce:conversation:"


class DebounceTracker:
    """Tracks per-conversation debounce windows in Redis.

    Each `touch()` call (re)sets a TTL key for the conversation with a fresh
    token. `is_stale()` lets a scheduled debounce-check coroutine detect
    whether a newer message has superseded it before it fires — see the
    Etapa 4 design's "Debounce trigger mechanism" ADR (`asyncio.create_task`
    + sleep-then-recheck, no ARQ).
    """

    def __init__(self, redis: Redis, debounce_seconds: int) -> None:
        self._redis = redis
        self._debounce_seconds = debounce_seconds

    def _key(self, conversation_id: str) -> str:
        return f"{_KEY_PREFIX}{conversation_id}"

    async def touch(self, conversation_id: str) -> str:
        """(Re)start the debounce window for a conversation, returning the new touch token."""
        token = uuid.uuid4().hex
        await self._redis.set(
            self._key(conversation_id),
            token,
            px=self._debounce_seconds * 1000,
        )
        return token

    async def is_stale(self, conversation_id: str, token: str) -> bool:
        """True when a later `touch()` superseded `token` before this check ran.

        A missing key (naturally expired, no re-touch) means `token` is still
        the latest — returns `False` so the caller proceeds.
        """
        current = await self._redis.get(self._key(conversation_id))
        if current is None:
            return False
        if isinstance(current, bytes):
            current = current.decode()
        return current != token

    async def clear(self, conversation_id: str) -> None:
        """Clears a conversation's pending debounce window.

        Admin-only, testing-tool operation — backs the "reset conversation"
        use case (`ResetConversationUseCase`), never called from the live
        message-ingestion path.
        """
        await self._redis.delete(self._key(conversation_id))
