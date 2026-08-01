from dataclasses import dataclass


@dataclass
class OutboxEvent:
    """Minimal outbox event shell, sized to type gateway Protocol signatures."""

    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, object]
    status: str
    attempts: int
