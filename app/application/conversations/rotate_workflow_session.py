from datetime import datetime, timedelta

from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId


class RotateWorkflowSessionUseCase:
    """Advance operational state without touching durable conversation data."""

    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    @staticmethod
    def is_inactive(previous_activity_at: datetime | None, received_at: datetime) -> bool:
        return previous_activity_at is not None and received_at - previous_activity_at > timedelta(
            hours=1
        )

    async def execute(self, conversation_id: ConversationId, *, expected_generation: int) -> bool:
        return await self._conversations.rotate_workflow_session(
            conversation_id, expected_generation
        )
