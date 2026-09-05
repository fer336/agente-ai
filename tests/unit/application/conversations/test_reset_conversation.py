from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.application.conversations.reset_conversation import ResetConversationUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.entities.contact_memory import ContactMemory
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.redis.debounce import DebounceTracker
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.seed_objects import make_conversation, make_message


def _make_use_case(
    conversation_repository=None,
    message_repository=None,
    contact_memory_repository=None,
    checkpointer=None,
    redis=None,
):
    conversation_repository = conversation_repository or FakeConversationRepository()
    message_repository = message_repository or FakeMessageRepository()
    contact_memory_repository = contact_memory_repository or FakeContactMemoryRepository()
    checkpointer = checkpointer or MemorySaver()
    redis = redis or InMemoryFakeRedis()
    memory_service = MemoryService(
        contact_memory_repository=contact_memory_repository,
        message_repository=message_repository,
        llm_provider=FakeLLMProvider(),
        recent_window_size=15,
        redis_client=redis,
    )
    use_case = ResetConversationUseCase(
        conversation_repository=conversation_repository,
        message_repository=message_repository,
        memory_service=memory_service,
        checkpointer=checkpointer,
        debounce_tracker=DebounceTracker(redis, debounce_seconds=8),
    )
    return (
        use_case,
        conversation_repository,
        message_repository,
        contact_memory_repository,
        checkpointer,
        redis,
    )


@pytest.mark.asyncio
async def test_execute_wipes_messages_memory_checkpoint_mode_and_debounce():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="human", input_state="HUMAN")
    )
    message_repository = FakeMessageRepository()
    await message_repository.save(make_message(id_="msg-1", conversation_id="conv-1"))
    await message_repository.save(make_message(id_="msg-2", conversation_id="conv-1"))
    contact_memory_repository = FakeContactMemoryRepository()
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id="contact-1",
            summary="resumen viejo",
            last_compacted_message_id="msg-1",
            last_compacted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": "conv-1", "checkpoint_ns": ""}}
    checkpointer.put(
        config,
        {"v": 1, "ts": "2024-01-01T00:00:00+00:00", "id": "chk-1", "channel_values": {}},
        {},
        {},
    )
    redis = InMemoryFakeRedis()
    debounce_tracker = DebounceTracker(redis, debounce_seconds=8)
    await debounce_tracker.touch("conv-1")

    use_case, *_ = _make_use_case(
        conversation_repository=conversation_repository,
        message_repository=message_repository,
        contact_memory_repository=contact_memory_repository,
        checkpointer=checkpointer,
        redis=redis,
    )

    result = await use_case.execute(ConversationId("conv-1"))

    assert result is not None
    assert result.mode == "agent"
    assert result.input_state == "FREE_INPUT"
    assert await message_repository.get_by_conversation_id(ConversationId("conv-1")) == []
    assert await contact_memory_repository.get_by_contact_id("contact-1") is None
    assert checkpointer.get(config) is None
    assert await redis.get("debounce:conversation:conv-1") is None


@pytest.mark.asyncio
async def test_execute_returns_none_when_conversation_does_not_exist():
    use_case, *_ = _make_use_case()

    result = await use_case.execute(ConversationId("missing"))

    assert result is None
