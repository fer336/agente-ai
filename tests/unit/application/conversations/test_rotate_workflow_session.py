import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.pending_actions.confirm_pending_action import ConfirmPendingActionUseCase
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_pending_action_repository import FakePendingActionRepository
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from tests.fixtures.seed_objects import make_pending_action, make_scheduled_action


@pytest.mark.asyncio
async def test_rotate_uses_generation_compare_and_swap_and_resets_input_state() -> None:
    repository = FakeConversationRepository()
    conversation = Conversation(
        id=ConversationId("ycloud-54911"),
        contact_id="contact-1",
        mode="agent",
        created_at=datetime.now(UTC),
        input_state="SENSITIVE_CONFIRMATION",
        workflow_session_generation=3,
    )
    await repository.save(conversation)

    use_case = RotateWorkflowSessionUseCase(repository)

    assert await use_case.execute(conversation.id, expected_generation=3) is True
    assert await use_case.execute(conversation.id, expected_generation=3) is False
    stored = await repository.get_by_id(conversation.id)
    assert stored is not None
    assert stored.workflow_session_generation == 4
    assert stored.input_state == "FREE_INPUT"


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (None, False),
        (timedelta(minutes=59, seconds=59), False),
        (timedelta(hours=1), False),
        (timedelta(hours=1, microseconds=1), True),
    ],
)
def test_inactivity_boundary_is_strictly_greater_than_one_hour(
    elapsed: timedelta | None, expected: bool
) -> None:
    received_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    previous = None if elapsed is None else received_at - elapsed

    assert RotateWorkflowSessionUseCase.is_inactive(previous, received_at) is expected


def _workflow_repositories_provider(
    conversations: FakeConversationRepository,
    pending_actions: FakePendingActionRepository,
    scheduled_actions: FakeScheduledActionRepository,
):
    @asynccontextmanager
    async def provider() -> AsyncIterator[object]:
        yield RotateWorkflowSessionUseCase.Repositories(
            conversations=conversations,
            pending_actions=pending_actions,
            scheduled_actions=scheduled_actions,
        )

    return provider


@pytest.mark.asyncio
async def test_successful_rotation_expires_only_pending_actions_from_the_old_generation() -> None:
    conversations = FakeConversationRepository()
    pending_actions = FakePendingActionRepository()
    scheduled_actions = FakeScheduledActionRepository()
    conversation = Conversation(
        id=ConversationId("conv-rotation"),
        contact_id="contact-1",
        mode="agent",
        created_at=datetime.now(UTC),
        workflow_session_generation=3,
    )
    await conversations.save(conversation)
    await pending_actions.save(
        make_pending_action(
            id_="old-pending", conversation_id="conv-rotation", workflow_generation=3
        )
    )
    await scheduled_actions.save(
        make_scheduled_action(
            id_="old-scheduled",
            conversation_id="conv-rotation",
            pending_action_id="old-pending",
            workflow_generation=3,
        )
    )
    await pending_actions.save(
        make_pending_action(
            id_="terminal-confirmed",
            conversation_id="conv-rotation",
            status="confirmed",
            workflow_generation=3,
        )
    )
    await scheduled_actions.save(
        make_scheduled_action(
            id_="terminal-completed",
            conversation_id="conv-rotation",
            pending_action_id="terminal-confirmed",
            status="completed",
            workflow_generation=3,
        )
    )
    await pending_actions.save(
        make_pending_action(
            id_="new-pending", conversation_id="conv-rotation", workflow_generation=4
        )
    )
    await scheduled_actions.save(
        make_scheduled_action(
            id_="new-scheduled",
            conversation_id="conv-rotation",
            pending_action_id="new-pending",
            workflow_generation=4,
        )
    )

    rotate = RotateWorkflowSessionUseCase(
        _workflow_repositories_provider(conversations, pending_actions, scheduled_actions)
    )

    assert await rotate.execute(conversation.id, expected_generation=3) is True
    assert (await pending_actions.get_by_id("old-pending")).status == "expired"
    assert (await scheduled_actions.get_by_id("old-scheduled")).status == "cancelled"
    assert (await pending_actions.get_by_id("terminal-confirmed")).status == "confirmed"
    assert (await scheduled_actions.get_by_id("terminal-completed")).status == "completed"
    assert (await pending_actions.get_by_id("new-pending")).status == "pending"
    assert (await scheduled_actions.get_by_id("new-scheduled")).status == "scheduled"


@pytest.mark.asyncio
async def test_confirmation_and_rotation_have_exactly_one_pending_action_winner() -> None:
    conversations = FakeConversationRepository()
    pending_actions = FakePendingActionRepository()
    scheduled_actions = FakeScheduledActionRepository()
    conversation = Conversation(
        id=ConversationId("conv-race"),
        contact_id="contact-1",
        mode="agent",
        created_at=datetime.now(UTC),
        workflow_session_generation=2,
    )
    await conversations.save(conversation)
    await pending_actions.save(
        make_pending_action(id_="race-pending", conversation_id="conv-race", workflow_generation=2)
    )
    await scheduled_actions.save(
        make_scheduled_action(
            id_="race-scheduled",
            conversation_id="conv-race",
            pending_action_id="race-pending",
            workflow_generation=2,
        )
    )

    rotate = RotateWorkflowSessionUseCase(
        _workflow_repositories_provider(conversations, pending_actions, scheduled_actions)
    )
    confirm = ConfirmPendingActionUseCase(pending_actions)
    results = await asyncio.gather(
        rotate.execute(conversation.id, expected_generation=2),
        confirm.execute("race-pending"),
        return_exceptions=True,
    )

    action = await pending_actions.get_by_id("race-pending")
    assert action is not None
    # Exactly ONE guarded transition wins the race: the other side observes
    # status != "pending" and either returns False (rotation) or raises
    # PendingActionExpiredError (confirmation). The action itself can never
    # end in both states — and whichever wins, the action is no longer pending.
    assert action.status in {"confirmed", "expired"}
    assert sum(result is True for result in results) == 1
