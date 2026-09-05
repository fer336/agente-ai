from app.domain.entities.contact_memory import ContactMemory


class FakeContactMemoryRepository:
    """In-memory fake implementing `ContactMemoryRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_contact_id: dict[str, ContactMemory] = {}

    async def get_by_contact_id(self, contact_id: str) -> ContactMemory | None:
        return self._by_contact_id.get(contact_id)

    async def save(self, memory: ContactMemory) -> None:
        self._by_contact_id[memory.contact_id] = memory

    async def delete(self, contact_id: str) -> None:
        self._by_contact_id.pop(contact_id, None)
