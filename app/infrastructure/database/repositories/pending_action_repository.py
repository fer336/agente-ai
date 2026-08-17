from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.pending_action import PendingActionModel


class SqlAlchemyPendingActionRepository:
    """`PendingActionRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, pending_action_id: str) -> PendingAction | None:
        model = await self._session.get(PendingActionModel, pending_action_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, pending_action: PendingAction) -> None:
        model = await self._session.get(PendingActionModel, pending_action.id)
        if model is None:
            model = PendingActionModel(id=pending_action.id)
            self._session.add(model)

        model.conversation_id = str(pending_action.conversation_id)
        model.action_type = pending_action.action_type
        model.payload = pending_action.payload
        model.confirmation_token = str(pending_action.confirmation_token)
        model.status = pending_action.status
        model.expires_at = pending_action.expires_at
        await self._session.flush()

    async def get_pending_for_conversation(
        self, conversation_id: ConversationId
    ) -> list[PendingAction]:
        result = await self._session.execute(
            select(PendingActionModel).where(
                PendingActionModel.conversation_id == str(conversation_id),
                PendingActionModel.status == "pending",
            )
        )
        return [_to_entity(model) for model in result.scalars()]

    async def mark_expired_if_pending(self, pending_action_id: str) -> bool:
        result = await self._session.execute(
            update(PendingActionModel)
            .where(
                PendingActionModel.id == pending_action_id,
                PendingActionModel.status == "pending",
            )
            .values(status="expired")
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1

    async def mark_confirmed_if_pending(self, pending_action_id: str) -> bool:
        result = await self._session.execute(
            update(PendingActionModel)
            .where(
                PendingActionModel.id == pending_action_id,
                PendingActionModel.status == "pending",
            )
            .values(status="confirmed")
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1


def _to_entity(model: PendingActionModel) -> PendingAction:
    return PendingAction(
        id=model.id,
        conversation_id=ConversationId(value=model.conversation_id),
        action_type=model.action_type,
        payload=model.payload,
        confirmation_token=ConfirmationToken(value=model.confirmation_token),
        status=model.status,
        expires_at=model.expires_at,
    )
