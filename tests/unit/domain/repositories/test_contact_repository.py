from app.domain.repositories.contact_repository import ContactRepository


class ConformingContactRepository:
    async def get_by_phone(self, phone):
        return None

    async def get_by_id(self, contact_id):
        return None

    async def save(self, contact):
        return None

    async def mark_review_opt_out(self, phone, opted_out_at):
        return False

    async def is_review_opted_out(self, phone):
        return False


class PartialContactRepository:
    async def get_by_phone(self, phone):
        return None


def test_conforming_class_satisfies_contact_repository_protocol():
    assert isinstance(ConformingContactRepository(), ContactRepository)


def test_partial_class_does_not_satisfy_contact_repository_protocol():
    assert not isinstance(PartialContactRepository(), ContactRepository)
