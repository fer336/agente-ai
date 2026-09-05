from datetime import UTC, datetime

import pytest

from app.domain.entities.contact_memory import ContactMemory
from app.infrastructure.database.fake_contact_memory_repository import FakeContactMemoryRepository


def _memory(contact_id: str = "contact-1", summary: str = "resumen") -> ContactMemory:
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    return ContactMemory(
        id=f"mem-{contact_id}",
        contact_id=contact_id,
        summary=summary,
        last_compacted_message_id=None,
        last_compacted_at=None,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_get_by_contact_id_returns_none_when_missing():
    repository = FakeContactMemoryRepository()

    assert await repository.get_by_contact_id("missing") is None


@pytest.mark.asyncio
async def test_save_then_get_by_contact_id_round_trips():
    repository = FakeContactMemoryRepository()
    memory = _memory()

    await repository.save(memory)

    assert await repository.get_by_contact_id("contact-1") == memory


@pytest.mark.asyncio
async def test_save_overwrites_the_existing_row_for_the_same_contact():
    repository = FakeContactMemoryRepository()
    await repository.save(_memory(summary="primer resumen"))

    await repository.save(_memory(summary="resumen actualizado"))

    result = await repository.get_by_contact_id("contact-1")
    assert result is not None
    assert result.summary == "resumen actualizado"


@pytest.mark.asyncio
async def test_delete_removes_the_row():
    repository = FakeContactMemoryRepository()
    await repository.save(_memory())

    await repository.delete("contact-1")

    assert await repository.get_by_contact_id("contact-1") is None


@pytest.mark.asyncio
async def test_delete_is_a_noop_when_no_memory_exists():
    repository = FakeContactMemoryRepository()

    await repository.delete("missing")
