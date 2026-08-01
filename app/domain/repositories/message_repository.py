from typing import Protocol, runtime_checkable

from app.domain.entities.message import Message
from app.domain.value_objects.external_message_id import ExternalMessageId


@runtime_checkable
class MessageRepository(Protocol):
    """Port to durable storage for messages."""

    async def exists_by_external_id(self, external_message_id: ExternalMessageId) -> bool: ...

    async def save(self, message: Message) -> None: ...
