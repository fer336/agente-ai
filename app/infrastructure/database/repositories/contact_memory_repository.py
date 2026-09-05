from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.contact_memory import ContactMemory
from app.infrastructure.database.models.contact_memory import ContactMemoryModel


class SqlAlchemyContactMemoryRepository:
    """`ContactMemoryRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_contact_id(self, contact_id: str) -> ContactMemory | None:
        result = await self._session.execute(
            select(ContactMemoryModel).where(ContactMemoryModel.contact_id == contact_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, memory: ContactMemory) -> None:
        result = await self._session.execute(
            select(ContactMemoryModel).where(ContactMemoryModel.contact_id == memory.contact_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = ContactMemoryModel(id=memory.id, contact_id=memory.contact_id)
            self._session.add(model)

        model.summary = memory.summary
        model.last_compacted_message_id = memory.last_compacted_message_id
        model.last_compacted_at = memory.last_compacted_at
        model.updated_at = memory.updated_at
        await self._session.flush()

    async def delete(self, contact_id: str) -> None:
        await self._session.execute(
            delete(ContactMemoryModel).where(ContactMemoryModel.contact_id == contact_id)
        )
        await self._session.flush()


def _to_entity(model: ContactMemoryModel) -> ContactMemory:
    return ContactMemory(
        id=model.id,
        contact_id=model.contact_id,
        summary=model.summary,
        last_compacted_message_id=model.last_compacted_message_id,
        last_compacted_at=model.last_compacted_at,
        updated_at=model.updated_at,
    )
