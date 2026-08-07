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
