from typing import Protocol, runtime_checkable

from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping


@runtime_checkable
class ChatwootMappingRepository(Protocol):
    """Port to the conversation_id -> Chatwoot contact/conversation
    correlation store. See `ChatwootConversationMapping`'s own docstring
    for why this exists."""

    async def save(self, mapping: ChatwootConversationMapping) -> None: ...

    async def get_by_conversation_id(
        self, conversation_id: str
    ) -> ChatwootConversationMapping | None: ...
