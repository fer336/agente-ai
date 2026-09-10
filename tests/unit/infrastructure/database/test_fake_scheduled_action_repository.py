from datetime import UTC, datetime, timedelta

import pytest

from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from tests.fixtures.gateways import make_scheduled_action_repository
from tests.fixtures.seed_objects import make_scheduled_action


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_scheduled_action_repository()
    scheduled_action = make_scheduled_action(id_="sa-1")

    await repository.save(scheduled_action)
    fetched = await repository.get_by_id("sa-1")

    assert fetched is scheduled_action


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_scheduled_action_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_due_returns_only_scheduled_actions_due_by_now():
    repository = make_scheduled_action_repository()
    now = datetime.now(UTC)
    await repository.save(
        make_scheduled_action(
            id_="sa-due", status="scheduled", scheduled_for=now - timedelta(seconds=5)
        )
    )
    await repository.save(
        make_scheduled_action(
            id_="sa-not-due", status="scheduled", scheduled_for=now + timedelta(seconds=60)
        )
    )
    await repository.save(
        make_scheduled_action(
            id_="sa-completed", status="completed", scheduled_for=now - timedelta(seconds=5)
        )
    )

    due = await repository.get_due(now, limit=10)

    assert [action.id for action in due] == ["sa-due"]


@pytest.mark.asyncio
async def test_transition_status_succeeds_when_status_matches():
    repository = make_scheduled_action_repository()
    await repository.save(make_scheduled_action(id_="sa-1", status="scheduled"))

    won = await repository.transition_status("sa-1", from_status="scheduled", to_status="cancelled")

    assert won is True
    fetched = await repository.get_by_id("sa-1")
    assert fetched is not None
    assert fetched.status == "cancelled"


@pytest.mark.asyncio
async def test_transition_status_fails_when_status_does_not_match():
    repository = make_scheduled_action_repository()
    await repository.save(make_scheduled_action(id_="sa-1", status="completed"))

    won = await repository.transition_status("sa-1", from_status="scheduled", to_status="cancelled")

    assert won is False


@pytest.mark.asyncio
async def test_get_by_pending_action_id_returns_the_matching_scheduled_action():
    repository = make_scheduled_action_repository()
    scheduled_action = make_scheduled_action(id_="sa-1", pending_action_id="pa-1")
    await repository.save(scheduled_action)

    fetched = await repository.get_by_pending_action_id("pa-1")

    assert fetched is scheduled_action


@pytest.mark.asyncio
async def test_get_by_pending_action_id_returns_none_when_no_match():
    repository = make_scheduled_action_repository()

    assert await repository.get_by_pending_action_id("missing") is None


def test_fake_scheduled_action_repository_satisfies_protocol():
    assert isinstance(FakeScheduledActionRepository(), ScheduledActionRepository)


@pytest.mark.asyncio
async def test_get_scheduled_by_conversation_id_returns_only_scheduled_rows_for_that_conversation():
    repository = make_scheduled_action_repository()
    await repository.save(
        make_scheduled_action(id_="sa-mine", conversation_id="conv-1", status="scheduled")
    )
    await repository.save(
        make_scheduled_action(id_="sa-mine-done", conversation_id="conv-1", status="cancelled")
    )
    await repository.save(
        make_scheduled_action(id_="sa-other", conversation_id="conv-2", status="scheduled")
    )

    found = await repository.get_scheduled_by_conversation_id("conv-1")

    assert [action.id for action in found] == ["sa-mine"]


@pytest.mark.asyncio
async def test_save_accepts_no_pending_action_for_an_inactivity_follow_up():
    repository = make_scheduled_action_repository()
    scheduled_action = make_scheduled_action(id_="sa-follow-up", pending_action_id=None)

    await repository.save(scheduled_action)

    fetched = await repository.get_by_id("sa-follow-up")
    assert fetched is not None
    assert fetched.pending_action_id is None
