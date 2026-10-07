from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.conversations.start_fresh_session import StartFreshSessionUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.entities.contact import Contact
from app.domain.entities.contact_memory import ContactMemory
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository

PHONE = PhoneNumber("+5491112345678")
NOW = datetime(2026, 10, 2, tzinfo=UTC)


def _memory() -> ContactMemory:
    return ContactMemory(
        id="m1",
        contact_id="c1",
        summary="s",
        last_compacted_message_id=None,
        last_compacted_at=None,
        updated_at=NOW,
    )


class Harness:
    def __init__(self) -> None:
        self.contacts = FakeContactRepository()
        self.conversations = FakeConversationRepository()
        self.memories = FakeContactMemoryRepository()
        memory_service = MemoryService(
            contact_memory_repository=self.memories,
            message_repository=None,  # type: ignore[arg-type]
            llm_provider=None,  # type: ignore[arg-type]
            recent_window_size=10,
        )
        self.use_case = StartFreshSessionUseCase(self.contacts, self.conversations, memory_service)

    async def seed(
        self, *, mode: str = "agent", conversation_contact_id: str = "c1", generation: int = 2
    ) -> None:
        await self.contacts.save(Contact(id="c1", phone=PHONE, patient_id="p1"))
        await self.conversations.save(
            Conversation(
                id=ConversationId(f"ycloud-{PHONE}"),
                contact_id=conversation_contact_id,
                mode=mode,
                created_at=NOW,
                workflow_session_generation=generation,
            )
        )
        await self.memories.save(_memory())

    async def generation(self) -> int:
        stored = await self.conversations.get_by_id(ConversationId(f"ycloud-{PHONE}"))
        assert stored is not None
        return stored.workflow_session_generation


@pytest.mark.asyncio
async def test_rotates_generation_and_resets_memory() -> None:
    h = Harness()
    await h.seed()

    assert await h.use_case.execute(PHONE) == "rotated"
    assert await h.generation() == 3
    assert await h.memories.get_by_contact_id("c1") is None


@pytest.mark.asyncio
async def test_unknown_contact_is_skipped() -> None:
    h = Harness()

    assert await h.use_case.execute(PHONE) == "contact_not_found"


@pytest.mark.asyncio
async def test_missing_conversation_keeps_memory() -> None:
    h = Harness()
    await h.contacts.save(Contact(id="c1", phone=PHONE, patient_id="p1"))
    await h.memories.save(_memory())

    assert await h.use_case.execute(PHONE) == "conversation_not_found"
    assert await h.memories.get_by_contact_id("c1") is not None


@pytest.mark.asyncio
async def test_non_agent_mode_keeps_context() -> None:
    h = Harness()
    await h.seed(mode="human")

    assert await h.use_case.execute(PHONE) == "not_agent_mode"
    assert await h.generation() == 2
    assert await h.memories.get_by_contact_id("c1") is not None


@pytest.mark.asyncio
async def test_contact_mismatch_is_skipped() -> None:
    h = Harness()
    await h.seed(conversation_contact_id="other")

    assert await h.use_case.execute(PHONE) == "contact_mismatch"
    assert await h.generation() == 2
    assert await h.memories.get_by_contact_id("c1") is not None


@pytest.mark.asyncio
async def test_lost_cas_race_keeps_memory() -> None:
    h = Harness()
    await h.seed()
    real_get = h.conversations.get_by_id

    async def stale_get(conversation_id: ConversationId) -> Conversation | None:
        found = await real_get(conversation_id)
        assert found is not None
        snapshot = replace(found)  # the fake mutates in place; keep the stale view
        # A concurrent rotation lands after this read.
        await h.conversations.rotate_workflow_session(conversation_id, 2)
        return snapshot

    h.conversations.get_by_id = stale_get  # type: ignore[method-assign]

    assert await h.use_case.execute(PHONE) == "rotation_lost"
    assert await h.generation() == 3
    assert await h.memories.get_by_contact_id("c1") is not None
