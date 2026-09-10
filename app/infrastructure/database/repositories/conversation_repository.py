from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
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
        model.last_human_reply_at = conversation.last_human_reply_at
        model.workflow_session_generation = conversation.workflow_session_generation
        model.workflow_last_activity_at = conversation.workflow_last_activity_at
        model.awaiting_fresh_restart = conversation.awaiting_fresh_restart
        await self._session.flush()

    async def rotate_workflow_session(
        self, conversation_id: ConversationId, expected_generation: int
    ) -> bool:
        result = await self._session.execute(
            update(ConversationModel)
            .where(
                ConversationModel.id == str(conversation_id),
                ConversationModel.workflow_session_generation == expected_generation,
            )
            .values(
                workflow_session_generation=expected_generation + 1,
                input_state="FREE_INPUT",
            )
        )
        await self._session.flush()
        return bool(cast(CursorResult[object], result).rowcount)

    async def list_recent(self, limit: int = 50) -> list[Conversation]:
        result = await self._session.execute(
            select(ConversationModel).order_by(ConversationModel.created_at.desc()).limit(limit)
        )
        return [_to_entity(model) for model in result.scalars().all()]


def _to_entity(model: ConversationModel) -> Conversation:
    return Conversation(
        id=ConversationId(value=model.id),
        contact_id=model.contact_id,
        mode=model.mode,
        created_at=model.created_at,
        input_state=model.input_state,
        last_human_reply_at=model.last_human_reply_at,
        workflow_session_generation=model.workflow_session_generation,
        workflow_last_activity_at=model.workflow_last_activity_at,
        awaiting_fresh_restart=model.awaiting_fresh_restart,
    )
