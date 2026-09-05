from app.domain.repositories.contact_memory_repository import ContactMemoryRepository


class ConformingContactMemoryRepository:
    async def get_by_contact_id(self, contact_id):
        return None

    async def save(self, memory):
        return None

    async def delete(self, contact_id):
        return None


class PartialContactMemoryRepository:
    async def get_by_contact_id(self, contact_id):
        return None


def test_conforming_class_satisfies_contact_memory_repository_protocol():
    assert isinstance(ConformingContactMemoryRepository(), ContactMemoryRepository)


def test_partial_class_does_not_satisfy_contact_memory_repository_protocol():
    assert not isinstance(PartialContactMemoryRepository(), ContactMemoryRepository)
