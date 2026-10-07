from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import MemorySaver

from app.domain.repositories.session_checkpoint_repository import SessionCheckpointRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.agent.fake_session_checkpoint_repository import (
    FakeSessionCheckpointRepository,
)
from app.infrastructure.agent.langgraph_session_checkpoint_repository import (
    LangGraphSessionCheckpointRepository,
)


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def _put(checkpointer: MemorySaver, thread_id: str) -> None:
    checkpointer.put(
        _config(thread_id),  # type: ignore[arg-type]
        {**empty_checkpoint(), "id": f"chk-{thread_id}"},
        {},
        {},
    )


def _has(checkpointer: MemorySaver, thread_id: str) -> bool:
    return checkpointer.get(_config(thread_id)) is not None  # type: ignore[arg-type]


def test_both_implementations_satisfy_the_port():
    assert isinstance(
        LangGraphSessionCheckpointRepository(MemorySaver()), SessionCheckpointRepository
    )
    assert isinstance(FakeSessionCheckpointRepository(), SessionCheckpointRepository)


@pytest.mark.asyncio
async def test_langgraph_repository_deletes_every_generation_of_the_target_conversation_only():
    checkpointer = MemorySaver()
    for thread_id in (
        "conv-1:session:1",
        "conv-1:session:2",
        "conv-1:session:3",
        "conv-1:session:4",  # beyond the requested range: untouched
        "conv-10:session:1",  # prefix lookalike
        "xconv-1:session:1",  # suffix lookalike
        "conv-2:session:1",
        "conv-1",  # bare legacy id: not a session thread
    ):
        _put(checkpointer, thread_id)

    await LangGraphSessionCheckpointRepository(checkpointer).delete_generations(
        ConversationId("conv-1"), up_to_generation=3
    )

    for deleted in ("conv-1:session:1", "conv-1:session:2", "conv-1:session:3"):
        assert not _has(checkpointer, deleted)
    for kept in (
        "conv-1:session:4",
        "conv-10:session:1",
        "xconv-1:session:1",
        "conv-2:session:1",
        "conv-1",
    ):
        assert _has(checkpointer, kept)


@pytest.mark.asyncio
async def test_langgraph_repository_is_idempotent():
    checkpointer = MemorySaver()
    _put(checkpointer, "conv-1:session:1")
    _put(checkpointer, "conv-2:session:1")
    repository = LangGraphSessionCheckpointRepository(checkpointer)

    await repository.delete_generations(ConversationId("conv-1"), up_to_generation=2)
    await repository.delete_generations(ConversationId("conv-1"), up_to_generation=2)

    assert not _has(checkpointer, "conv-1:session:1")
    assert _has(checkpointer, "conv-2:session:1")


@pytest.mark.asyncio
async def test_fake_repository_records_exact_thread_ids_and_is_idempotent():
    repository = FakeSessionCheckpointRepository(
        threads={"conv-1:session:1", "conv-1:session:2", "conv-10:session:1", "xconv-1:session:1"}
    )

    await repository.delete_generations(ConversationId("conv-1"), up_to_generation=2)
    await repository.delete_generations(ConversationId("conv-1"), up_to_generation=2)

    assert repository.threads == {"conv-10:session:1", "xconv-1:session:1"}
    assert repository.calls == [("conv-1", 2), ("conv-1", 2)]


@pytest.mark.asyncio
async def test_non_positive_generation_deletes_nothing():
    checkpointer = MemorySaver()
    _put(checkpointer, "conv-1:session:1")

    await LangGraphSessionCheckpointRepository(checkpointer).delete_generations(
        ConversationId("conv-1"), up_to_generation=0
    )

    assert _has(checkpointer, "conv-1:session:1")
