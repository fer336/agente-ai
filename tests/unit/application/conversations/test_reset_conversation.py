from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.application.conversations.reset_conversation import ResetConversationUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.entities.contact_memory import ContactMemory
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_agent_run_repository import FakeAgentRunRepository
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_error_repository import FakeErrorRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.database.fake_node_execution_repository import (
    FakeNodeExecutionRepository,
)
from app.infrastructure.database.fake_tool_execution_repository import (
    FakeToolExecutionRepository,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.redis.debounce import DebounceTracker
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_conversation,
    make_error_record,
    make_message,
    make_node_execution,
    make_tool_execution,
)


def _make_use_case(
    conversation_repository=None,
    message_repository=None,
    contact_memory_repository=None,
    checkpointer=None,
    redis=None,
    agent_run_repository=None,
    node_execution_repository=None,
    tool_execution_repository=None,
    error_repository=None,
):
    conversation_repository = conversation_repository or FakeConversationRepository()
    message_repository = message_repository or FakeMessageRepository()
    contact_memory_repository = contact_memory_repository or FakeContactMemoryRepository()
    checkpointer = checkpointer or MemorySaver()
    redis = redis or InMemoryFakeRedis()
    agent_run_repository = agent_run_repository or FakeAgentRunRepository()
    node_execution_repository = node_execution_repository or FakeNodeExecutionRepository()
    tool_execution_repository = tool_execution_repository or FakeToolExecutionRepository()
    error_repository = error_repository or FakeErrorRepository()
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
        agent_run_repository=agent_run_repository,
        node_execution_repository=node_execution_repository,
        tool_execution_repository=tool_execution_repository,
        error_repository=error_repository,
    )
    return (
        use_case,
        conversation_repository,
        message_repository,
        contact_memory_repository,
        checkpointer,
        redis,
        agent_run_repository,
        node_execution_repository,
        tool_execution_repository,
        error_repository,
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
async def test_execute_deletes_agent_runs_and_their_node_and_tool_executions_first():
    # Reproduces a live production failure: deleting a message that a real
    # `agent_runs` row still references (`agent_runs.message_id` is a plain
    # FK, no cascade) raised `ForeignKeyViolationError`. Node/tool
    # executions and errors hang off the agent_run the same way and must
    # go first too.
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", contact_id="contact-1"))
    message_repository = FakeMessageRepository()
    await message_repository.save(make_message(id_="msg-1", conversation_id="conv-1"))
    agent_run_repository = FakeAgentRunRepository()
    await agent_run_repository.save(
        make_agent_run(id_="run-1", conversation_id="conv-1", message_id="msg-1")
    )
    node_execution_repository = FakeNodeExecutionRepository()
    await node_execution_repository.save(make_node_execution(id_="ne-1", agent_run_id="run-1"))
    tool_execution_repository = FakeToolExecutionRepository()
    await tool_execution_repository.save(
        make_tool_execution(id_="te-1", agent_run_id="run-1", node_execution_id="ne-1")
    )
    error_repository = FakeErrorRepository()
    await error_repository.save(
        make_error_record(id_="err-1", conversation_id="conv-1", agent_run_id="run-1")
    )

    use_case, *_ = _make_use_case(
        conversation_repository=conversation_repository,
        message_repository=message_repository,
        agent_run_repository=agent_run_repository,
        node_execution_repository=node_execution_repository,
        tool_execution_repository=tool_execution_repository,
        error_repository=error_repository,
    )

    result = await use_case.execute(ConversationId("conv-1"))

    assert result is not None
    assert await agent_run_repository.get_by_conversation_id(ConversationId("conv-1")) == []
    assert await node_execution_repository.get_by_agent_run_id("run-1") == []
    assert await tool_execution_repository.get_by_agent_run_id("run-1") == []
    assert await error_repository.get_by_conversation_id(ConversationId("conv-1")) == []


@pytest.mark.asyncio
async def test_execute_deletes_errors_linked_only_by_agent_run_id():
    # Reproduces a second live production failure: `with_error_handling`
    # reports errors with `agent_run_id` set but `conversation_id` left
    # `None` (see `error_service.report`'s call sites) — deleting by
    # conversation_id alone misses these, and they then block deleting
    # the agent_run itself via `errors_agent_run_id_fkey`.
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", contact_id="contact-1"))
    message_repository = FakeMessageRepository()
    await message_repository.save(make_message(id_="msg-1", conversation_id="conv-1"))
    agent_run_repository = FakeAgentRunRepository()
    await agent_run_repository.save(
        make_agent_run(id_="run-1", conversation_id="conv-1", message_id="msg-1")
    )
    error_repository = FakeErrorRepository()
    await error_repository.save(
        make_error_record(id_="err-1", conversation_id=None, agent_run_id="run-1")
    )

    use_case, *_ = _make_use_case(
        conversation_repository=conversation_repository,
        message_repository=message_repository,
        agent_run_repository=agent_run_repository,
        error_repository=error_repository,
    )

    result = await use_case.execute(ConversationId("conv-1"))

    assert result is not None
    assert await error_repository.get_by_id("err-1") is None


@pytest.mark.asyncio
async def test_execute_returns_none_when_conversation_does_not_exist():
    use_case, *_ = _make_use_case()

    result = await use_case.execute(ConversationId("missing"))

    assert result is None
