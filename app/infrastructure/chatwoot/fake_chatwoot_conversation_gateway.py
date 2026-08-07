class FakeChatwootConversationGateway:
    """In-memory fake implementing `ChatwootConversationGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.mirrored_messages: list[tuple[str, str]] = []

    async def mirror_message(self, chatwoot_conversation_id: str, text: str) -> None:
        self.mirrored_messages.append((chatwoot_conversation_id, text))
