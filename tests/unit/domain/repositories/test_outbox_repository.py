from app.domain.repositories.outbox_repository import OutboxRepository


class ConformingOutboxRepository:
    async def save(self, event):
        return None

    async def fetch_pending(self, limit):
        return []

    async def mark_processed(self, event_id):
        return None


class PartialOutboxRepository:
    async def save(self, event):
        return None


def test_conforming_class_satisfies_outbox_repository_protocol():
    assert isinstance(ConformingOutboxRepository(), OutboxRepository)


def test_partial_class_does_not_satisfy_outbox_repository_protocol():
    assert not isinstance(PartialOutboxRepository(), OutboxRepository)
