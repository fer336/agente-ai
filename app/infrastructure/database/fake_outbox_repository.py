from app.domain.entities.outbox_event import OutboxEvent


class FakeOutboxRepository:
    """In-memory fake implementing `OutboxRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, OutboxEvent] = {}

    async def save(self, event: OutboxEvent) -> None:
        self._by_id[event.id] = event

    async def fetch_pending(self, limit: int) -> list[OutboxEvent]:
        pending = [event for event in self._by_id.values() if event.status == "pending"]
        return pending[:limit]

    async def mark_processed(self, event_id: str) -> None:
        event = self._by_id.get(event_id)
        if event is None:
            raise ValueError(f"OutboxEvent {event_id} not found")
        event.status = "processed"
