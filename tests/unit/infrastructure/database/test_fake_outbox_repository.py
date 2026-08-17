import pytest

from app.domain.repositories.outbox_repository import OutboxRepository
from app.infrastructure.database.fake_outbox_repository import FakeOutboxRepository
from tests.fixtures.gateways import make_outbox_repository
from tests.fixtures.seed_objects import make_outbox_event


@pytest.mark.asyncio
async def test_save_then_fetch_pending_returns_the_event():
    repository = make_outbox_repository()
    event = make_outbox_event(id_="evt-1")

    await repository.save(event)
    pending = await repository.fetch_pending(limit=10)

    assert [item.id for item in pending] == ["evt-1"]


@pytest.mark.asyncio
async def test_mark_processed_excludes_the_event_from_fetch_pending():
    repository = make_outbox_repository()
    await repository.save(make_outbox_event(id_="evt-2"))

    await repository.mark_processed("evt-2")
    pending = await repository.fetch_pending(limit=10)

    assert pending == []


@pytest.mark.asyncio
async def test_mark_processed_raises_when_event_does_not_exist():
    repository = make_outbox_repository()

    with pytest.raises(ValueError, match="not found"):
        await repository.mark_processed("missing")


def test_fake_outbox_repository_satisfies_protocol():
    assert isinstance(FakeOutboxRepository(), OutboxRepository)
