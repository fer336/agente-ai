from datetime import UTC, datetime

from app.domain.entities.contact_memory import ContactMemory
from app.infrastructure.database.repositories.contact_memory_repository import (
    SqlAlchemyContactMemoryRepository,
)


def _memory(contact_id: str, summary: str = "resumen") -> ContactMemory:
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    return ContactMemory(
        id=f"mem-{contact_id}",
        contact_id=contact_id,
        summary=summary,
        last_compacted_message_id=None,
        last_compacted_at=None,
        updated_at=now,
    )


async def test_get_by_contact_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyContactMemoryRepository(db_session)

    assert await repository.get_by_contact_id("missing") is None


async def test_save_then_get_by_contact_id_round_trips(db_session, contact_id):
    repository = SqlAlchemyContactMemoryRepository(db_session)

    await repository.save(_memory(contact_id))
    fetched = await repository.get_by_contact_id(contact_id)

    assert fetched is not None
    assert fetched.contact_id == contact_id
    assert fetched.summary == "resumen"


async def test_save_overwrites_the_existing_row_for_the_same_contact(db_session, contact_id):
    repository = SqlAlchemyContactMemoryRepository(db_session)
    await repository.save(_memory(contact_id, summary="primer resumen"))

    await repository.save(_memory(contact_id, summary="resumen actualizado"))

    fetched = await repository.get_by_contact_id(contact_id)
    assert fetched is not None
    assert fetched.summary == "resumen actualizado"


async def test_delete_removes_the_row(db_session, contact_id):
    repository = SqlAlchemyContactMemoryRepository(db_session)
    await repository.save(_memory(contact_id))

    await repository.delete(contact_id)

    assert await repository.get_by_contact_id(contact_id) is None


async def test_delete_is_a_noop_when_no_memory_exists(db_session, contact_id):
    repository = SqlAlchemyContactMemoryRepository(db_session)

    await repository.delete(contact_id)
