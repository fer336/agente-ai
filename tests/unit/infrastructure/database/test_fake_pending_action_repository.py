import pytest

from app.domain.repositories.pending_action_repository import PendingActionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_pending_action_repository import FakePendingActionRepository
from tests.fixtures.gateways import make_pending_action_repository
from tests.fixtures.seed_objects import make_pending_action


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_pending_action_repository()
    pending_action = make_pending_action(id_="pa-1")

    await repository.save(pending_action)
    fetched = await repository.get_by_id("pa-1")

    assert fetched is pending_action


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_pending_action_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_pending_for_conversation_excludes_non_pending_actions():
    repository = make_pending_action_repository()
    await repository.save(
        make_pending_action(id_="pa-1", conversation_id="conv-1", status="pending")
    )
    await repository.save(
        make_pending_action(id_="pa-2", conversation_id="conv-1", status="confirmed")
    )

    pending = await repository.get_pending_for_conversation(ConversationId("conv-1"))

    assert {action.id for action in pending} == {"pa-1"}


@pytest.mark.asyncio
async def test_mark_expired_if_pending_succeeds_when_still_pending():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="pending"))

    expired = await repository.mark_expired_if_pending("pa-1")

    assert expired is True
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "expired"


@pytest.mark.asyncio
async def test_mark_expired_if_pending_fails_when_already_confirmed():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="confirmed"))

    expired = await repository.mark_expired_if_pending("pa-1")

    assert expired is False
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "confirmed"


@pytest.mark.asyncio
async def test_mark_confirmed_if_pending_succeeds_when_still_pending():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="pending"))

    confirmed = await repository.mark_confirmed_if_pending("pa-1")

    assert confirmed is True
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "confirmed"


@pytest.mark.asyncio
async def test_mark_confirmed_if_pending_fails_when_already_expired():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="expired"))

    confirmed = await repository.mark_confirmed_if_pending("pa-1")

    assert confirmed is False
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "expired"


def test_fake_pending_action_repository_satisfies_protocol():
    assert isinstance(FakePendingActionRepository(), PendingActionRepository)
