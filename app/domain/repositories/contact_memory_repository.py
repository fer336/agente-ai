from typing import Protocol, runtime_checkable

from app.domain.entities.contact_memory import ContactMemory


@runtime_checkable
class ContactMemoryRepository(Protocol):
    """Port to durable storage for `ContactMemory` (conversational-memory module)."""

    async def get_by_contact_id(self, contact_id: str) -> ContactMemory | None: ...

    async def save(self, memory: ContactMemory) -> None:
        """Upsert semantics — inserts a new row, or overwrites the existing
        one for this `contact_id` (there is at most one per contact).
        """
        ...

    async def delete(self, contact_id: str) -> None:
        """No-op if no memory exists for this contact yet."""
        ...
