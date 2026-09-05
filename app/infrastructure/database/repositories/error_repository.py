from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.error_record import ErrorRecord
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.error_record import ErrorModel


class SqlAlchemyErrorRepository:
    """`ErrorRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, error_id: str) -> ErrorRecord | None:
        model = await self._session.get(ErrorModel, error_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, error: ErrorRecord) -> None:
        model = await self._session.get(ErrorModel, error.id)
        if model is None:
            model = ErrorModel(id=error.id)
            self._session.add(model)

        model.trace_id = error.trace_id
        model.conversation_id = str(error.conversation_id) if error.conversation_id else None
        model.agent_run_id = error.agent_run_id
        model.source = error.source
        model.error_type = error.error_type
        model.error_code = error.error_code
        model.message = error.message
        model.technical_detail = error.technical_detail
        model.severity = error.severity
        model.retryable = error.retryable
        model.created_at = error.created_at
        model.resolved_at = error.resolved_at
        await self._session.flush()

    async def count_recent(self, source: str, error_type: str, since: datetime) -> int:
        result = await self._session.execute(
            select(func.count()).where(
                ErrorModel.source == source,
                ErrorModel.error_type == error_type,
                ErrorModel.created_at >= since,
            )
        )
        return result.scalar_one()

    async def list_recent(self, limit: int = 50) -> list[ErrorRecord]:
        result = await self._session.execute(
            select(ErrorModel).order_by(ErrorModel.created_at.desc()).limit(limit)
        )
        return [_to_entity(model) for model in result.scalars().all()]

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[ErrorRecord]:
        result = await self._session.execute(
            select(ErrorModel)
            .where(ErrorModel.conversation_id == str(conversation_id))
            .order_by(ErrorModel.created_at.desc())
        )
        return [_to_entity(model) for model in result.scalars().all()]

    async def delete_by_conversation_id(self, conversation_id: ConversationId) -> None:
        result = await self._session.execute(
            select(ErrorModel).where(ErrorModel.conversation_id == str(conversation_id))
        )
        for model in result.scalars().all():
            await self._session.delete(model)
        await self._session.flush()


def _to_entity(model: ErrorModel) -> ErrorRecord:
    return ErrorRecord(
        id=model.id,
        trace_id=model.trace_id,
        conversation_id=ConversationId(value=model.conversation_id)
        if model.conversation_id
        else None,
        agent_run_id=model.agent_run_id,
        source=model.source,
        error_type=model.error_type,
        error_code=model.error_code,
        message=model.message,
        technical_detail=model.technical_detail,
        severity=model.severity,
        retryable=model.retryable,
        created_at=model.created_at,
        resolved_at=model.resolved_at,
    )
