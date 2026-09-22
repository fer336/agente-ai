from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping


class FakeChatwootMappingRepository:
    """In-memory fake implementing `ChatwootMappingRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_conversation_id: dict[str, ChatwootConversationMapping] = {}

    async def save(self, mapping: ChatwootConversationMapping) -> None:
        self._by_conversation_id[mapping.conversation_id] = mapping

    async def get_by_conversation_id(
        self, conversation_id: str
    ) -> ChatwootConversationMapping | None:
        return self._by_conversation_id.get(conversation_id)

    async def get_by_chatwoot_conversation_id(
        self, chatwoot_conversation_id: str
    ) -> ChatwootConversationMapping | None:
        for mapping in self._by_conversation_id.values():
            if mapping.chatwoot_conversation_id == chatwoot_conversation_id:
                return mapping
        return None
