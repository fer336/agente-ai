from datetime import UTC, datetime

import pytest

from app.application.memory.memory_service import MemoryService
from app.domain.entities.contact_memory import ContactMemory
from app.domain.entities.message import ROLE_ASSISTANT, ROLE_USER, Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.infrastructure.database.fake_contact_memory_repository import FakeContactMemoryRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.fake_redis import InMemoryFakeRedis

_CONVERSATION_ID = ConversationId("ycloud-+5491122334455")
_CONTACT_ID = "contact-1"
_NOW = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


class _BrokenRedis:
    """A Redis client whose every call raises — proves `MemoryService` falls
    back to PostgreSQL rather than propagating a cache outage.
    """

    async def get(self, name: str) -> bytes | None:
        raise ConnectionError("redis unreachable")

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        raise ConnectionError("redis unreachable")

    async def delete(self, name: str) -> None:
        raise ConnectionError("redis unreachable")


def _message(
    message_id: str, text: str, created_at: datetime, direction: str = "inbound", role=None
) -> Message:
    return Message(
        id=message_id,
        conversation_id=_CONVERSATION_ID,
        external_message_id=ExternalMessageId(f"wamid.{message_id}"),
        direction=direction,
        text=text,
        created_at=created_at,
        role=role,
    )


def _build_service(
    message_repository: FakeMessageRepository | None = None,
    contact_memory_repository: FakeContactMemoryRepository | None = None,
    llm_provider: FakeLLMProvider | None = None,
    recent_window_size: int = 15,
    redis_client=None,
) -> tuple[MemoryService, FakeMessageRepository, FakeContactMemoryRepository]:
    message_repository = message_repository or FakeMessageRepository()
    contact_memory_repository = contact_memory_repository or FakeContactMemoryRepository()
    service = MemoryService(
        contact_memory_repository=contact_memory_repository,
        message_repository=message_repository,
        llm_provider=llm_provider or FakeLLMProvider(),
        recent_window_size=recent_window_size,
        redis_client=redis_client,
        cache_ttl_seconds=3600,
    )
    return service, message_repository, contact_memory_repository


@pytest.mark.asyncio
async def test_get_recent_messages_respects_the_window_size():
    message_repository = FakeMessageRepository()
    for i in range(5):
        await message_repository.save(
            _message(f"msg-{i}", f"mensaje {i}", datetime(2026, 8, 31, 9, i, tzinfo=UTC))
        )
    service, _, _ = _build_service(message_repository=message_repository, recent_window_size=2)

    recent = await service.get_recent_messages(_CONVERSATION_ID)

    assert [m.id for m in recent] == ["msg-3", "msg-4"]


@pytest.mark.asyncio
async def test_get_contact_memory_returns_none_when_nothing_exists():
    service, _, _ = _build_service()

    assert await service.get_contact_memory(_CONTACT_ID) is None


@pytest.mark.asyncio
async def test_get_contact_memory_cache_miss_reads_postgres_and_populates_cache():
    contact_memory_repository = FakeContactMemoryRepository()
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="Juan Perez, ortodoncia",
            last_compacted_message_id="msg-4",
            last_compacted_at=now,
            updated_at=now,
        )
    )
    redis = InMemoryFakeRedis()
    service, _, _ = _build_service(
        contact_memory_repository=contact_memory_repository, redis_client=redis
    )

    memory = await service.get_contact_memory(_CONTACT_ID)

    assert memory is not None
    assert memory.summary == "Juan Perez, ortodoncia"
    # Populated the cache on miss.
    assert await redis.get(f"memory:contact:{_CONTACT_ID}:summary") is not None


@pytest.mark.asyncio
async def test_get_contact_memory_cache_hit_never_touches_postgres():
    contact_memory_repository = FakeContactMemoryRepository()
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="resumen original",
            last_compacted_message_id="msg-1",
            last_compacted_at=now,
            updated_at=now,
        )
    )
    redis = InMemoryFakeRedis()
    service, _, _ = _build_service(
        contact_memory_repository=contact_memory_repository, redis_client=redis
    )
    await service.get_contact_memory(_CONTACT_ID)  # warms the cache

    # Mutate Postgres directly without invalidating the cache — a cache hit
    # must return the (now-stale) cached value, proving it never re-reads.
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="resumen cambiado a mano en postgres",
            last_compacted_message_id="msg-1",
            last_compacted_at=now,
            updated_at=now,
        )
    )

    memory = await service.get_contact_memory(_CONTACT_ID)

    assert memory is not None
    assert memory.summary == "resumen original"


@pytest.mark.asyncio
async def test_get_contact_memory_falls_back_to_postgres_when_redis_is_down():
    contact_memory_repository = FakeContactMemoryRepository()
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="Juan Perez",
            last_compacted_message_id=None,
            last_compacted_at=None,
            updated_at=now,
        )
    )
    service, _, _ = _build_service(
        contact_memory_repository=contact_memory_repository, redis_client=_BrokenRedis()
    )

    memory = await service.get_contact_memory(_CONTACT_ID)

    assert memory is not None
    assert memory.summary == "Juan Perez"


@pytest.mark.asyncio
async def test_build_agent_context_falls_back_to_direction_when_role_is_none():
    message_repository = FakeMessageRepository()
    await message_repository.save(
        _message("msg-1", "hola", datetime(2026, 8, 31, 9, 0, tzinfo=UTC), direction="inbound")
    )
    await message_repository.save(
        _message(
            "msg-2", "hola, en que te ayudo", datetime(2026, 8, 31, 9, 1, tzinfo=UTC),
            direction="outbound",
        )
    )
    service, _, _ = _build_service(message_repository=message_repository)

    recent_messages, contact_memory = await service.build_agent_context(
        _CONVERSATION_ID, _CONTACT_ID
    )

    assert recent_messages == [
        {"role": ROLE_USER, "content": "hola"},
        {"role": ROLE_ASSISTANT, "content": "hola, en que te ayudo"},
    ]
    assert contact_memory is None


@pytest.mark.asyncio
async def test_build_agent_context_uses_explicit_role_over_direction():
    message_repository = FakeMessageRepository()
    await message_repository.save(
        _message(
            "msg-1", "hola", datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
            direction="inbound", role=ROLE_ASSISTANT,
        )
    )
    service, _, _ = _build_service(message_repository=message_repository)

    recent_messages, _ = await service.build_agent_context(_CONVERSATION_ID, _CONTACT_ID)

    assert recent_messages == [{"role": ROLE_ASSISTANT, "content": "hola"}]


@pytest.mark.asyncio
async def test_record_outbound_message_persists_with_assistant_role():
    message_repository = FakeMessageRepository()
    service, _, _ = _build_service(message_repository=message_repository)

    saved = await service.record_outbound_message(
        _CONVERSATION_ID, "Hola Juan", datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    )

    assert saved.direction == "outbound"
    assert saved.role == ROLE_ASSISTANT
    fetched = await message_repository.get_by_id(saved.id)
    assert fetched is not None
    assert fetched.text == "Hola Juan"


@pytest.mark.asyncio
async def test_compact_is_a_noop_when_there_are_no_new_messages():
    service, message_repository, contact_memory_repository = _build_service()

    memory = await service.compact(_CONTACT_ID, _CONVERSATION_ID)

    assert memory.summary == ""
    assert memory.last_compacted_message_id is None


@pytest.mark.asyncio
async def test_compact_summarizes_only_messages_after_the_watermark():
    message_repository = FakeMessageRepository()
    contact_memory_repository = FakeContactMemoryRepository()
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="Juan Perez",
            last_compacted_message_id="msg-1",
            last_compacted_at=now,
            updated_at=now,
        )
    )
    await message_repository.save(_message("msg-1", "hola", now))
    await message_repository.save(_message("msg-2", "quiero un turno", now.replace(minute=1)))
    service, _, _ = _build_service(
        message_repository=message_repository, contact_memory_repository=contact_memory_repository
    )

    memory = await service.compact(_CONTACT_ID, _CONVERSATION_ID)

    # FakeLLMProvider.summarize concatenates previous_summary + new lines —
    # "hola" (msg-1, already compacted) must NOT reappear in the new summary.
    assert "Juan Perez" in memory.summary
    assert "hola" not in memory.summary
    assert "quiero un turno" in memory.summary
    assert memory.last_compacted_message_id == "msg-2"


@pytest.mark.asyncio
async def test_compact_from_scratch_summarizes_the_full_history():
    message_repository = FakeMessageRepository()
    await message_repository.save(_message("msg-1", "hola", _NOW))
    service, _, _ = _build_service(message_repository=message_repository)

    memory = await service.compact(_CONTACT_ID, _CONVERSATION_ID)

    assert "hola" in memory.summary
    assert memory.last_compacted_message_id == "msg-1"


@pytest.mark.asyncio
async def test_compact_invalidates_the_cache():
    message_repository = FakeMessageRepository()
    await message_repository.save(_message("msg-1", "hola", _NOW))
    redis = InMemoryFakeRedis()
    await redis.set(f"memory:contact:{_CONTACT_ID}:summary", "stale-cached-value")
    service, _, _ = _build_service(message_repository=message_repository, redis_client=redis)

    await service.compact(_CONTACT_ID, _CONVERSATION_ID)

    assert await redis.get(f"memory:contact:{_CONTACT_ID}:summary") is None


@pytest.mark.asyncio
async def test_reset_clears_memory_but_not_messages():
    message_repository = FakeMessageRepository()
    contact_memory_repository = FakeContactMemoryRepository()
    await message_repository.save(_message("msg-1", "hola", _NOW))
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id=_CONTACT_ID,
            summary="resumen",
            last_compacted_message_id="msg-1",
            last_compacted_at=_NOW,
            updated_at=_NOW,
        )
    )
    service, _, _ = _build_service(
        message_repository=message_repository, contact_memory_repository=contact_memory_repository
    )

    await service.reset(_CONTACT_ID)

    assert await contact_memory_repository.get_by_contact_id(_CONTACT_ID) is None
    assert await message_repository.get_by_id("msg-1") is not None


@pytest.mark.asyncio
async def test_invalidate_cache_with_no_redis_client_is_a_noop():
    service, _, _ = _build_service(redis_client=None)

    await service.invalidate_cache(_CONTACT_ID)
