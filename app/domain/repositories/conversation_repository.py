from typing import Protocol, runtime_checkable

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class ConversationRepository(Protocol):
    """Port to durable storage for conversations."""

    async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None: ...

    async def save(self, conversation: Conversation) -> None: ...
