from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId


class FakeMessageRepository:
    """In-memory fake implementing `MessageRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._messages_by_id: dict[str, Message] = {}

    async def exists_by_external_id(self, external_message_id: ExternalMessageId) -> bool:
        return any(
            message.external_message_id == external_message_id
            for message in self._messages_by_id.values()
        )

    async def save(self, message: Message) -> None:
        self._messages_by_id[message.id] = message

    async def get_by_id(self, message_id: str) -> Message | None:
        return self._messages_by_id.get(message_id)

    async def update(self, message: Message) -> None:
        if message.id not in self._messages_by_id:
            raise ValueError(f"Message {message.id} not found")
        self._messages_by_id[message.id] = message

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[Message]:
        matches = [
            message
            for message in self._messages_by_id.values()
            if message.conversation_id == conversation_id
        ]
        return sorted(matches, key=lambda m: m.created_at)
