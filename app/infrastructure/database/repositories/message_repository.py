from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
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
            message_type=message.message_type,
            media_id=message.media_id,
            media_mime_type=message.media_mime_type,
            media_sha256=message.media_sha256,
            media_status=message.media_status,
            inbound_received_at=message.inbound_received_at,
            transcription=message.transcription,
            transcription_status=message.transcription_status,
            transcription_provider=message.transcription_provider,
            transcription_model=message.transcription_model,
            transcription_duration_ms=message.transcription_duration_ms,
            transcription_error=message.transcription_error,
            role=message.role,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, message_id: str) -> Message | None:
        model = await self._session.get(MessageModel, message_id)
        if model is None:
            return None
        return _to_entity(model)

    async def update(self, message: Message) -> None:
        model = await self._session.get(MessageModel, message.id)
        if model is None:
            raise ValueError(f"Message {message.id} not found")

        model.text = message.text
        model.message_type = message.message_type
        model.media_id = message.media_id
        model.media_mime_type = message.media_mime_type
        model.media_sha256 = message.media_sha256
        model.media_status = message.media_status
        model.inbound_received_at = message.inbound_received_at
        model.transcription = message.transcription
        model.transcription_status = message.transcription_status
        model.transcription_provider = message.transcription_provider
        model.transcription_model = message.transcription_model
        model.transcription_duration_ms = message.transcription_duration_ms
        model.transcription_error = message.transcription_error
        await self._session.flush()

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[Message]:
        result = await self._session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.asc())
        )
        return [_to_entity(model) for model in result.scalars().all()]

    async def get_recent_by_conversation_id(
        self, conversation_id: ConversationId, limit: int
    ) -> list[Message]:
        if limit <= 0:
            return []
        result = await self._session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        recent_newest_first = [_to_entity(model) for model in result.scalars().all()]
        return list(reversed(recent_newest_first))

    async def get_by_conversation_id_after(
        self, conversation_id: ConversationId, after_message_id: str | None
    ) -> list[Message]:
        query = select(MessageModel).where(MessageModel.conversation_id == str(conversation_id))
        if after_message_id is not None:
            anchor = await self._session.get(MessageModel, after_message_id)
            if anchor is not None:
                query = query.where(MessageModel.created_at > anchor.created_at)
        query = query.order_by(MessageModel.created_at.asc())
        result = await self._session.execute(query)
        return [_to_entity(model) for model in result.scalars().all()]

    async def delete_by_conversation_id(self, conversation_id: ConversationId) -> None:
        result = await self._session.execute(
            select(MessageModel).where(MessageModel.conversation_id == str(conversation_id))
        )
        for model in result.scalars().all():
            await self._session.delete(model)
        await self._session.flush()


def _to_entity(model: MessageModel) -> Message:
    return Message(
        id=model.id,
        conversation_id=ConversationId(model.conversation_id),
        external_message_id=ExternalMessageId(model.external_message_id),
        direction=model.direction,
        text=model.text,
        created_at=model.created_at,
        message_type=model.message_type,
        media_id=model.media_id,
        media_mime_type=model.media_mime_type,
        media_sha256=model.media_sha256,
        media_status=model.media_status,
        inbound_received_at=model.inbound_received_at,
        transcription=model.transcription,
        transcription_status=model.transcription_status,
        transcription_provider=model.transcription_provider,
        transcription_model=model.transcription_model,
        transcription_duration_ms=model.transcription_duration_ms,
        transcription_error=model.transcription_error,
        role=model.role,
    )
