from unittest.mock import AsyncMock

from app.api.dependencies.session_cleanup import build_idle_cleanup_use_case
from app.application.conversations.schedule_conversation_reset import (
    ScheduleConversationResetUseCase,
)
from app.workers.follow_up_worker import FollowUpWorkerRepositories


def _repositories(reminders):
    return FollowUpWorkerRepositories(
        scheduled_actions=AsyncMock(),
        messages=AsyncMock(),
        conversations=AsyncMock(),
        contacts=AsyncMock(),
        contact_memories=AsyncMock(),
        appointment_reminders=reminders,
        pending_actions=AsyncMock(),
    )


def test_idle_cleanup_is_wired_with_the_reminder_guard_and_the_reset_scheduler():
    reminders = AsyncMock()

    use_case = build_idle_cleanup_use_case(_repositories(reminders), checkpointer=object())

    assert use_case is not None
    assert use_case._appointment_reminders is reminders
    assert isinstance(use_case._schedule_conversation_reset, ScheduleConversationResetUseCase)


def test_idle_cleanup_without_a_reminder_repository_has_no_guard():
    use_case = build_idle_cleanup_use_case(_repositories(None), checkpointer=object())

    assert use_case is not None
    assert use_case._appointment_reminders is None


async def test_idle_cleanup_rotates_inside_the_ticks_own_transaction(monkeypatch):
    """The tick already holds row locks (its claim); a second session would wait on them."""

    def opens_another_session():
        raise AssertionError("the cleanup must not open a second database session")

    monkeypatch.setattr(
        "app.api.dependencies.session_cleanup.open_sqlalchemy_workflow_session_repositories",
        opens_another_session,
        raising=False,
    )
    repositories = _repositories(None)
    repositories.conversations.rotate_workflow_session.return_value = True
    repositories.pending_actions.get_pending_for_conversation.return_value = []

    use_case = build_idle_cleanup_use_case(repositories, checkpointer=object())

    assert use_case is not None
    rotated = await use_case._rotate_workflow_session.execute(
        "conv-1", expected_generation=3, expire_all_pending_generations=True
    )
    assert rotated is True
    repositories.conversations.rotate_workflow_session.assert_awaited_once_with("conv-1", 3)
    repositories.pending_actions.get_pending_for_conversation.assert_awaited_once_with("conv-1")


def test_idle_cleanup_is_unavailable_without_the_tick_pending_action_repository():
    repositories = _repositories(None)
    repositories = FollowUpWorkerRepositories(
        scheduled_actions=repositories.scheduled_actions,
        messages=repositories.messages,
        conversations=repositories.conversations,
        contacts=repositories.contacts,
        contact_memories=repositories.contact_memories,
    )

    assert build_idle_cleanup_use_case(repositories, checkpointer=object()) is None
