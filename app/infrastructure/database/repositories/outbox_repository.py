from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.outbox_event import OutboxEvent
from app.infrastructure.database.models.outbox_event import OutboxEventModel


class SqlAlchemyOutboxRepository:
    """`OutboxRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, event: OutboxEvent) -> None:
        model = OutboxEventModel(
            id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            status=event.status,
            attempts=event.attempts,
        )
        self._session.add(model)
        await self._session.flush()

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.status == "pending",
                OutboxEventModel.available_at <= datetime.now(UTC),
            )
            .order_by(OutboxEventModel.available_at)
            .limit(limit)
        )
        return [_to_entity(model) for model in result.scalars()]

    async def mark_processed(self, event_id: str) -> None:
        model = await self._session.get(OutboxEventModel, event_id)
        if model is None:
            raise ValueError(f"OutboxEvent {event_id} not found")

        model.status = "processed"
        model.processed_at = datetime.now(UTC)
        await self._session.flush()


def _to_entity(model: OutboxEventModel) -> OutboxEvent:
    return OutboxEvent(
        id=model.id,
        event_type=model.event_type,
        aggregate_type=model.aggregate_type,
        aggregate_id=model.aggregate_id,
        payload=model.payload,
        status=model.status,
        attempts=model.attempts,
    )
