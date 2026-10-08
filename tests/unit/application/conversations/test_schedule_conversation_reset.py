from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
    ScheduleConversationResetUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from tests.fixtures.seed_objects import make_scheduled_action

CONVERSATION_ID = ConversationId("conv-1")
DELAY = 10_800
ANCHOR = datetime(2026, 10, 8, 13, 30, tzinfo=UTC)


async def idle_actions(repository, status="scheduled"):
    return [
        action
        for action in await repository.get_scheduled_by_conversation_id(str(CONVERSATION_ID))
        if action.action_type == CONVERSATION_IDLE_RESET_ACTION and action.status == status
    ]


@pytest.mark.asyncio
async def test_defer_after_schedules_one_idle_reset_at_the_anchor_plus_the_delay():
    repository = FakeScheduledActionRepository()

    await ScheduleConversationResetUseCase(repository, DELAY).defer_after(CONVERSATION_ID, ANCHOR)

    [action] = await idle_actions(repository)
    assert action.scheduled_for == ANCHOR + timedelta(seconds=DELAY)
    assert action.pending_action_id is None


@pytest.mark.asyncio
async def test_defer_after_is_idempotent_and_keeps_an_already_scheduled_idle_reset():
    repository = FakeScheduledActionRepository()
    use_case = ScheduleConversationResetUseCase(repository, DELAY)

    await use_case.defer_after(CONVERSATION_ID, ANCHOR)
    [first] = await idle_actions(repository)
    await use_case.defer_after(CONVERSATION_ID, ANCHOR + timedelta(hours=5))

    [only] = await idle_actions(repository)
    assert only.id == first.id
    assert only.scheduled_for == ANCHOR + timedelta(seconds=DELAY)


@pytest.mark.asyncio
async def test_defer_after_ignores_other_scheduled_actions_of_the_conversation():
    repository = FakeScheduledActionRepository()
    await repository.save(
        make_scheduled_action(id_="other", conversation_id="conv-1", action_type="something_else")
    )

    await ScheduleConversationResetUseCase(repository, DELAY).defer_after(CONVERSATION_ID, ANCHOR)

    assert len(await idle_actions(repository)) == 1


@pytest.mark.asyncio
async def test_defer_after_does_not_count_an_idle_reset_already_executed_or_cancelled():
    repository = FakeScheduledActionRepository()
    await repository.save(
        make_scheduled_action(
            id_="done",
            conversation_id="conv-1",
            action_type=CONVERSATION_IDLE_RESET_ACTION,
            status="executed",
        )
    )

    await ScheduleConversationResetUseCase(repository, DELAY).defer_after(CONVERSATION_ID, ANCHOR)

    assert len(await idle_actions(repository)) == 1
