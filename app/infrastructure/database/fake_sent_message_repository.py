from app.domain.entities.sent_message import SentMessage


class FakeSentMessageRepository:
    """In-memory fake implementing `SentMessageRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, SentMessage] = {}

    async def save(self, sent_message: SentMessage) -> None:
        self._by_id[sent_message.id] = sent_message

    async def get_by_id(self, message_id: str) -> SentMessage | None:
        return self._by_id.get(message_id)
