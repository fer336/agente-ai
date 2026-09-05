from datetime import UTC, datetime

import pytest

from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.workers.memory_tasks import compact_stale_contact_memories
from tests.fixtures.gateways import (
    make_contact_memory_repository,
    make_conversation_repository,
    make_memory_service,
    make_message_repository,
)
from tests.fixtures.seed_objects import make_conversation

_THRESHOLD = 3


def _message(conversation_id: str, message_id: str, created_at: datetime) -> Message:
    return Message(
        id=message_id,
        conversation_id=ConversationId(conversation_id),
        external_message_id=ExternalMessageId(f"wamid.{message_id}"),
        direction="inbound",
        text="hola",
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_compacts_a_contact_past_the_threshold():
    conversation_repository = make_conversation_repository()
    message_repository = make_message_repository()
    contact_memory_repository = make_contact_memory_repository()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    for i in range(4):
        await message_repository.save(
            _message("conv-1", f"msg-{i}", datetime(2026, 8, 31, 9, i, tzinfo=UTC))
        )
    memory_service = make_memory_service(
        message_repository=message_repository, contact_memory_repository=contact_memory_repository
    )

    count = await compact_stale_contact_memories(
        conversation_repository,
        contact_memory_repository,
        message_repository,
        memory_service,
        _THRESHOLD,
    )

    assert count == 1
    memory = await contact_memory_repository.get_by_contact_id("contact-1")
    assert memory is not None
    assert memory.last_compacted_message_id == "msg-3"


@pytest.mark.asyncio
async def test_leaves_a_contact_below_the_threshold_uncompacted():
    conversation_repository = make_conversation_repository()
    message_repository = make_message_repository()
    contact_memory_repository = make_contact_memory_repository()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    await message_repository.save(
        _message("conv-1", "msg-0", datetime(2026, 8, 31, 9, 0, tzinfo=UTC))
    )
    memory_service = make_memory_service(
        message_repository=message_repository, contact_memory_repository=contact_memory_repository
    )

    count = await compact_stale_contact_memories(
        conversation_repository,
        contact_memory_repository,
        message_repository,
        memory_service,
        _THRESHOLD,
    )

    assert count == 0
    assert await contact_memory_repository.get_by_contact_id("contact-1") is None


@pytest.mark.asyncio
async def test_only_counts_messages_after_the_existing_watermark():
    conversation_repository = make_conversation_repository()
    message_repository = make_message_repository()
    contact_memory_repository = make_contact_memory_repository()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    for i in range(2):
        await message_repository.save(
            _message("conv-1", f"msg-{i}", datetime(2026, 8, 31, 9, i, tzinfo=UTC))
        )
    memory_service = make_memory_service(
        message_repository=message_repository, contact_memory_repository=contact_memory_repository
    )
    # A prior compaction already watermarked msg-1 — only msg-2 is new,
    # below the threshold of 3.
    await memory_service.compact("contact-1", ConversationId("conv-1"))
    await message_repository.save(
        _message("conv-1", "msg-2", datetime(2026, 8, 31, 9, 5, tzinfo=UTC))
    )

    count = await compact_stale_contact_memories(
        conversation_repository,
        contact_memory_repository,
        message_repository,
        memory_service,
        _THRESHOLD,
    )

    assert count == 0


class _FailingMemoryService:
    async def compact(self, contact_id: str, conversation_id):
        raise RuntimeError("llm provider down")


@pytest.mark.asyncio
async def test_a_failing_compaction_does_not_abort_the_sweep():
    conversation_repository = make_conversation_repository()
    message_repository = make_message_repository()
    contact_memory_repository = make_contact_memory_repository()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    for i in range(4):
        await message_repository.save(
            _message("conv-1", f"msg-{i}", datetime(2026, 8, 31, 9, i, tzinfo=UTC))
        )

    count = await compact_stale_contact_memories(
        conversation_repository,
        contact_memory_repository,
        message_repository,
        _FailingMemoryService(),
        _THRESHOLD,
    )

    assert count == 0
