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
