import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from redis.asyncio import Redis

from app.domain.entities.contact_memory import ContactMemory
from app.domain.entities.message import ROLE_ASSISTANT, ROLE_USER, Message
from app.domain.repositories.contact_memory_repository import ContactMemoryRepository
from app.domain.repositories.llm_provider import LLMProvider, ResponseContext
from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "memory:contact:"


def _cache_key(contact_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{contact_id}:summary"


def _message_role(message: Message) -> str:
    """Falls back to `direction` for rows written before `role` existed."""
    if message.role is not None:
        return message.role
    return ROLE_USER if message.direction == "inbound" else ROLE_ASSISTANT


class MemoryService:
    """Conversational memory (no PRD.md section number — this session's own
    brief): assembles the bounded LLM-facing context (recent window +
    compacted per-contact summary) and owns incremental compaction.

    UNVERIFIED against a real LLM: this codebase has no real `LLMProvider`
    adapter yet (only `FakeLLMProvider`, see that module's own docstring) —
    `compact()`'s summarization quality is therefore untested against a real
    model, same honesty convention as `GroqTranscriptionGateway`/
    `TelegramAlertNotifier`'s "UNVERIFIED" docstrings elsewhere in this
    codebase. `compact()`'s STRUCTURE (incremental input, watermark
    advancement, cache invalidation) is fully tested against the Fake.

    Redis (`redis_client`) is a pure cache in front of PostgreSQL — never
    the source of truth. Any Redis failure on read falls back to PostgreSQL
    and logs a warning rather than raising; a `redis_client=None` disables
    caching entirely (every read goes straight to PostgreSQL), which is a
    valid, fully-functional configuration, not a degraded one.
    """

    def __init__(
        self,
        contact_memory_repository: ContactMemoryRepository,
        message_repository: MessageRepository,
        llm_provider: LLMProvider,
        recent_window_size: int,
        redis_client: Redis | None = None,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._contact_memory_repository = contact_memory_repository
        self._message_repository = message_repository
        self._llm_provider = llm_provider
        self._recent_window_size = recent_window_size
        self._redis_client = redis_client
        self._cache_ttl_seconds = cache_ttl_seconds

    async def get_recent_messages(self, conversation_id: ConversationId) -> list[Message]:
        return await self._message_repository.get_recent_by_conversation_id(
            conversation_id, self._recent_window_size
        )

    async def get_contact_memory(self, contact_id: str) -> ContactMemory | None:
        cached = await self._read_cache(contact_id)
        if cached is not None:
            logger.info(
                "memory_service.get_contact_memory cache_hit contact_id=%s",
                contact_id,
                extra={"contact_id": contact_id, "source": "cache"},
            )
            return cached

        memory = await self._contact_memory_repository.get_by_contact_id(contact_id)
        if memory is not None:
            await self._write_cache(memory)
        logger.info(
            "memory_service.get_contact_memory cache_miss contact_id=%s found=%s",
            contact_id,
            memory is not None,
            extra={"contact_id": contact_id, "source": "postgres"},
        )
        return memory

    async def build_agent_context(
        self, conversation_id: ConversationId, contact_id: str
    ) -> tuple[list[dict[str, str]], str | None]:
        """Returns `(recent_messages, contact_memory_summary)` in the plain,
        JSON-serializable shape `AgentState`'s two new keys hold — the
        single call site `LangGraphAgentInvoker.handle()` uses to populate
        them once per turn, before `graph.ainvoke()`.
        """
        recent = await self.get_recent_messages(conversation_id)
        memory = await self.get_contact_memory(contact_id)
        recent_messages = [
            {"role": _message_role(message), "content": message.text}
            for message in recent
            if message.text
        ]
        return recent_messages, (memory.summary if memory is not None else None)

    async def build_response_context(
        self,
        conversation_id: ConversationId,
        contact_id: str,
        intent: str,
        collected_data: dict[str, object],
    ) -> ResponseContext:
        """Convenience for a future NLG node — see this module's own report
        for why no node currently calls `LLMProvider.generate_response` yet.
        """
        recent_messages, contact_memory = await self.build_agent_context(
            conversation_id, contact_id
        )
        return ResponseContext(
            conversation_id=str(conversation_id),
            intent=intent,
            collected_data=collected_data,
            recent_messages=recent_messages,
            contact_memory=contact_memory,
        )

    async def record_outbound_message(
        self, conversation_id: ConversationId, text: str, now: datetime
    ) -> Message:
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            external_message_id=ExternalMessageId(f"outbound-{uuid4().hex}"),
            direction="outbound",
            text=text,
            created_at=now,
            role=ROLE_ASSISTANT,
        )
        await self._message_repository.save(message)
        return message

    async def compact(self, contact_id: str, conversation_id: ConversationId) -> ContactMemory:
        """Incremental compaction: `previous_summary + new_messages ->
        new_summary`. Never re-reads messages a prior compaction already
        folded in — `MessageRepository.get_by_conversation_id_after` only
        returns what's strictly newer than `last_compacted_message_id`.

        A no-op (returns the existing memory unchanged, still invalidates
        the cache) when there are no new messages — avoids
        `LLMProvider.summarize` calls, and log noise, for a contact that
        hasn't said anything since the last compaction.

        One row per contact, overwritten in place — no version history is
        kept (confirmed design decision: observability into "when did this
        change" is via the log line below, not a stored history table).
        """
        existing = await self._contact_memory_repository.get_by_contact_id(contact_id)
        previous_summary = existing.summary if existing is not None else ""
        last_compacted_message_id = existing.last_compacted_message_id if existing else None

        new_messages = await self._message_repository.get_by_conversation_id_after(
            conversation_id, last_compacted_message_id
        )
        now = datetime.now(UTC)

        if not new_messages:
            logger.info(
                "memory_service.compact noop contact_id=%s reason=no_new_messages",
                contact_id,
                extra={"contact_id": contact_id, "message_count": 0},
            )
            if existing is not None:
                return existing
            memory = ContactMemory(
                id=str(uuid4()),
                contact_id=contact_id,
                summary=previous_summary,
                last_compacted_message_id=None,
                last_compacted_at=None,
                updated_at=now,
            )
            await self._contact_memory_repository.save(memory)
            return memory

        new_summary = await self._llm_provider.summarize(previous_summary, new_messages)
        memory = ContactMemory(
            id=existing.id if existing is not None else str(uuid4()),
            contact_id=contact_id,
            summary=new_summary,
            last_compacted_message_id=new_messages[-1].id,
            last_compacted_at=now,
            updated_at=now,
        )
        await self._contact_memory_repository.save(memory)
        await self.invalidate_cache(contact_id)
        logger.info(
            "memory_service.compact done contact_id=%s message_count=%d summary_length=%d",
            contact_id,
            len(new_messages),
            len(new_summary),
            extra={
                "contact_id": contact_id,
                "message_count": len(new_messages),
                "summary_length": len(new_summary),
            },
        )
        return memory

    async def reset(self, contact_id: str) -> None:
        """Clears compacted memory + its cache. Never touches `messages` or
        LangGraph's checkpointed state — a separate, not-yet-requested
        action would be needed to purge raw history.
        """
        await self._contact_memory_repository.delete(contact_id)
        await self.invalidate_cache(contact_id)

    async def invalidate_cache(self, contact_id: str) -> None:
        if self._redis_client is None:
            return
        try:
            await self._redis_client.delete(_cache_key(contact_id))
        except Exception:  # noqa: BLE001 - cache invalidation must never break a write path
            logger.warning(
                "memory_service.invalidate_cache redis_error contact_id=%s",
                contact_id,
                exc_info=True,
            )

    async def _read_cache(self, contact_id: str) -> ContactMemory | None:
        if self._redis_client is None:
            return None
        try:
            raw = await self._redis_client.get(_cache_key(contact_id))
        except Exception:  # noqa: BLE001 - PostgreSQL is the source of truth, cache is optional
            logger.warning(
                "memory_service.get_contact_memory redis_read_error contact_id=%s",
                contact_id,
                exc_info=True,
            )
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(raw)
        return ContactMemory(
            id=payload["id"],
            contact_id=contact_id,
            summary=payload["summary"],
            last_compacted_message_id=payload["last_compacted_message_id"],
            last_compacted_at=(
                datetime.fromisoformat(payload["last_compacted_at"])
                if payload["last_compacted_at"]
                else None
            ),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
        )

    async def _write_cache(self, memory: ContactMemory) -> None:
        if self._redis_client is None:
            return
        payload = {
            "id": memory.id,
            "summary": memory.summary,
            "last_compacted_message_id": memory.last_compacted_message_id,
            "last_compacted_at": (
                memory.last_compacted_at.isoformat() if memory.last_compacted_at else None
            ),
            "updated_at": memory.updated_at.isoformat(),
        }
        try:
            await self._redis_client.set(
                _cache_key(memory.contact_id), json.dumps(payload), ex=self._cache_ttl_seconds
            )
        except Exception:  # noqa: BLE001 - a failed cache write must never break a read path
            logger.warning(
                "memory_service.get_contact_memory redis_write_error contact_id=%s",
                memory.contact_id,
                exc_info=True,
            )
