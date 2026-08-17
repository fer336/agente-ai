from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.conversation import ConversationModel


class SqlAlchemyConversationRepository:
    """`ConversationRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None:
        model = await self._session.get(ConversationModel, str(conversation_id))
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, conversation: Conversation) -> None:
        model = await self._session.get(ConversationModel, str(conversation.id))
        if model is None:
            model = ConversationModel(id=str(conversation.id))
            self._session.add(model)

        model.contact_id = conversation.contact_id
        model.mode = conversation.mode
        model.input_state = conversation.input_state
        model.created_at = conversation.created_at
        await self._session.flush()


def _to_entity(model: ConversationModel) -> Conversation:
    return Conversation(
        id=ConversationId(value=model.id),
        contact_id=model.contact_id,
        mode=model.mode,
        created_at=model.created_at,
        input_state=model.input_state,
    )
