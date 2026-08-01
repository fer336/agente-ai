from typing import Protocol, runtime_checkable

from app.domain.entities.outbox_event import OutboxEvent


@runtime_checkable
class OutboxRepository(Protocol):
    """Port to durable storage for the outbox pattern."""

    async def save(self, event: OutboxEvent) -> None: ...

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]: ...

    async def mark_processed(self, event_id: str) -> None: ...
