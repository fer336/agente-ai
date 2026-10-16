from datetime import UTC, datetime

import pytest

from app.domain.repositories.pending_action_repository import (
    ConfirmedActionReader,
    PendingActionRepository,
)
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


def test_fake_pending_action_repository_satisfies_confirmed_action_reader():
    assert isinstance(FakePendingActionRepository(), ConfirmedActionReader)


def _at(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


async def _seed(repository, id_, action_type, status, confirmed_at, **kwargs):
    action = make_pending_action(
        id_=id_, action_type=action_type, status=status, conversation_id="conv-1", **kwargs
    )
    await repository.save(action)
    if confirmed_at is not None:
        repository.set_confirmed_at(id_, confirmed_at)


@pytest.mark.asyncio
async def test_mark_confirmed_if_pending_records_confirmed_at_from_clock():
    repository = FakePendingActionRepository(clock=lambda: _at(12))
    await repository.save(make_pending_action(id_="pa-1", status="pending"))

    await repository.mark_confirmed_if_pending("pa-1")

    rows = await repository.list_confirmed_between({"create_appointment"}, _at(0), _at(23), 10)
    assert [row.confirmed_at for row in rows] == [_at(12)]


@pytest.mark.asyncio
async def test_list_confirmed_between_filters_type_status_and_half_open_period():
    repository = FakePendingActionRepository()
    await _seed(repository, "in", "create_appointment", "confirmed", _at(10))
    await _seed(repository, "at-start", "create_appointment", "confirmed", _at(8))
    await _seed(repository, "at-end", "create_appointment", "confirmed", _at(18))
    await _seed(repository, "before", "create_appointment", "confirmed", _at(7, 59))
    await _seed(repository, "other-type", "cancel_appointment", "confirmed", _at(10))
    await _seed(repository, "expired", "create_appointment", "expired", _at(10))
    await _seed(repository, "never-confirmed", "create_appointment", "confirmed", None)

    rows = await repository.list_confirmed_between({"create_appointment"}, _at(8), _at(18), 50)

    assert {row.id for row in rows} == {"in", "at-start"}


@pytest.mark.asyncio
async def test_list_confirmed_between_orders_newest_first_applies_limit_and_exposes_fields():
    repository = FakePendingActionRepository()
    for id_, hour in (("a", 9), ("b", 11), ("c", 10)):
        await _seed(
            repository,
            id_,
            "reschedule_appointment",
            "confirmed",
            _at(hour),
            payload={"professional_id": "7"},
        )

    rows = await repository.list_confirmed_between(
        {"create_appointment", "reschedule_appointment"}, _at(0), _at(23), 2
    )

    assert [row.id for row in rows] == ["b", "c"]
    first = rows[0]
    assert first.conversation_id == "conv-1"
    assert first.action_type == "reschedule_appointment"
    assert first.payload == {"professional_id": "7"}
    assert first.confirmed_at == _at(11)
