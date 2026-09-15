from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.sent_message import SentMessage
from app.infrastructure.database.models.sent_message import SentMessageModel


class SqlAlchemySentMessageRepository:
    """`SentMessageRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, sent_message: SentMessage) -> None:
        model = await self._session.get(SentMessageModel, sent_message.id)
        if model is None:
            model = SentMessageModel(id=sent_message.id)
            self._session.add(model)

        model.conversation_id = sent_message.conversation_id
        model.sent_at = sent_message.sent_at
        await self._session.flush()

    async def get_by_id(self, message_id: str) -> SentMessage | None:
        model = await self._session.get(SentMessageModel, message_id)
        if model is None:
            return None
        return SentMessage(
            id=model.id,
            conversation_id=model.conversation_id,
            sent_at=model.sent_at,
        )
