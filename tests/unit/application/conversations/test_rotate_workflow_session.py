from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository


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
