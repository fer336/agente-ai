from typing import Protocol, runtime_checkable

from app.domain.entities.sent_message import SentMessage


@runtime_checkable
class SentMessageRepository(Protocol):
    """Port to the outbound-message-id -> conversation_id correlation store."""

    async def save(self, sent_message: SentMessage) -> None: ...

    async def get_by_id(self, message_id: str) -> SentMessage | None: ...
