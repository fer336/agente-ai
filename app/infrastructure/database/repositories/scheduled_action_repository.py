from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey
from app.infrastructure.database.models.scheduled_action import ScheduledActionModel


class SqlAlchemyScheduledActionRepository:
    """`ScheduledActionRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, scheduled_action_id: str) -> ScheduledAction | None:
        model = await self._session.get(ScheduledActionModel, scheduled_action_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, scheduled_action: ScheduledAction) -> None:
        model = await self._session.get(ScheduledActionModel, scheduled_action.id)
        if model is None:
            model = ScheduledActionModel(id=scheduled_action.id)
            self._session.add(model)

        model.conversation_id = str(scheduled_action.conversation_id)
        model.pending_action_id = scheduled_action.pending_action_id
        model.action_type = scheduled_action.action_type
        model.status = scheduled_action.status
        model.scheduled_for = scheduled_action.scheduled_for
        model.idempotency_key = str(scheduled_action.idempotency_key)
        model.attempts = scheduled_action.attempts
        await self._session.flush()

    async def get_due(self, now: datetime, limit: int) -> list[ScheduledAction]:
        result = await self._session.execute(
            select(ScheduledActionModel)
            .where(
                ScheduledActionModel.status == "scheduled",
                ScheduledActionModel.scheduled_for <= now,
            )
            .order_by(ScheduledActionModel.scheduled_for)
            .limit(limit)
        )
        return [_to_entity(model) for model in result.scalars()]

    async def get_by_pending_action_id(self, pending_action_id: str) -> ScheduledAction | None:
        result = await self._session.execute(
            select(ScheduledActionModel).where(
                ScheduledActionModel.pending_action_id == pending_action_id
            )
        )
        model = result.scalars().first()
        if model is None:
            return None
        return _to_entity(model)

    async def transition_status(
        self, scheduled_action_id: str, *, from_status: str, to_status: str
    ) -> bool:
        result = await self._session.execute(
            update(ScheduledActionModel)
            .where(
                ScheduledActionModel.id == scheduled_action_id,
                ScheduledActionModel.status == from_status,
            )
            .values(status=to_status)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1


def _to_entity(model: ScheduledActionModel) -> ScheduledAction:
    return ScheduledAction(
        id=model.id,
        conversation_id=ConversationId(value=model.conversation_id),
        pending_action_id=model.pending_action_id,
        action_type=model.action_type,
        status=model.status,
        scheduled_for=model.scheduled_for,
        idempotency_key=IdempotencyKey(value=model.idempotency_key),
        attempts=model.attempts,
    )
