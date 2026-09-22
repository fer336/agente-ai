from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.infrastructure.database.models.chatwoot_conversation_mapping import (
    ChatwootConversationMappingModel,
)


class SqlAlchemyChatwootMappingRepository:
    """`ChatwootMappingRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, mapping: ChatwootConversationMapping) -> None:
        model = await self._session.get(
            ChatwootConversationMappingModel, mapping.conversation_id
        )
        if model is None:
            model = ChatwootConversationMappingModel(conversation_id=mapping.conversation_id)
            self._session.add(model)

        model.chatwoot_contact_id = mapping.chatwoot_contact_id
        model.chatwoot_conversation_id = mapping.chatwoot_conversation_id
        await self._session.flush()

    async def get_by_conversation_id(
        self, conversation_id: str
    ) -> ChatwootConversationMapping | None:
        model = await self._session.get(ChatwootConversationMappingModel, conversation_id)
        if model is None:
            return None
        return ChatwootConversationMapping(
            conversation_id=model.conversation_id,
            chatwoot_contact_id=model.chatwoot_contact_id,
            chatwoot_conversation_id=model.chatwoot_conversation_id,
        )

    async def get_by_chatwoot_conversation_id(
        self, chatwoot_conversation_id: str
    ) -> ChatwootConversationMapping | None:
        # No index on `chatwoot_conversation_id` — a full scan of this
        # small, one-row-per-real-conversation table, same tradeoff already
        # accepted for the migration itself (see 0018's own docstring).
        result = await self._session.execute(
            select(ChatwootConversationMappingModel).where(
                ChatwootConversationMappingModel.chatwoot_conversation_id
                == chatwoot_conversation_id
            )
        )
        model = result.scalars().first()
        if model is None:
            return None
        return ChatwootConversationMapping(
            conversation_id=model.conversation_id,
            chatwoot_contact_id=model.chatwoot_contact_id,
            chatwoot_conversation_id=model.chatwoot_conversation_id,
        )
