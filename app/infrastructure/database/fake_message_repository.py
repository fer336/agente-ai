from app.domain.entities.message import Message
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
