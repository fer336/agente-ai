from app.domain.repositories.contact_repository import ContactRepository


class ConformingContactRepository:
    async def get_by_phone(self, phone):
        return None

    async def save(self, contact):
        return None


class PartialContactRepository:
    async def get_by_phone(self, phone):
        return None


def test_conforming_class_satisfies_contact_repository_protocol():
    assert isinstance(ConformingContactRepository(), ContactRepository)


def test_partial_class_does_not_satisfy_contact_repository_protocol():
    assert not isinstance(PartialContactRepository(), ContactRepository)
