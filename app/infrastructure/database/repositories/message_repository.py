from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.message import Message
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.infrastructure.database.models.message import MessageModel


class SqlAlchemyMessageRepository:
    """`MessageRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists_by_external_id(self, external_message_id: ExternalMessageId) -> bool:
        result = await self._session.execute(
            select(MessageModel.id).where(
                MessageModel.external_message_id == str(external_message_id)
            )
        )
        return result.scalar_one_or_none() is not None

    async def save(self, message: Message) -> None:
        model = MessageModel(
            id=message.id,
            conversation_id=str(message.conversation_id),
            external_message_id=str(message.external_message_id),
            direction=message.direction,
            text=message.text,
            created_at=message.created_at,
        )
        self._session.add(model)
        await self._session.flush()
