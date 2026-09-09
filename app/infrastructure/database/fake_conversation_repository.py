from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId


class FakeConversationRepository:
    """In-memory fake implementing `ConversationRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._conversations_by_id: dict[str, Conversation] = {}

    async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None:
        return self._conversations_by_id.get(str(conversation_id))

    async def save(self, conversation: Conversation) -> None:
        self._conversations_by_id[str(conversation.id)] = conversation

    async def rotate_workflow_session(
        self, conversation_id: ConversationId, expected_generation: int
    ) -> bool:
        conversation = self._conversations_by_id.get(str(conversation_id))
        if conversation is None or conversation.workflow_session_generation != expected_generation:
            return False
        conversation.workflow_session_generation += 1
        conversation.input_state = "FREE_INPUT"
        return True

    async def list_recent(self, limit: int = 50) -> list[Conversation]:
        ordered = sorted(
            self._conversations_by_id.values(), key=lambda c: c.created_at, reverse=True
        )
        return ordered[:limit]
