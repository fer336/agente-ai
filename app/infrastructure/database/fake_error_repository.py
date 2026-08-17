from datetime import datetime

from app.domain.entities.error_record import ErrorRecord


class FakeErrorRepository:
    """In-memory fake implementing `ErrorRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, ErrorRecord] = {}

    async def get_by_id(self, error_id: str) -> ErrorRecord | None:
        return self._by_id.get(error_id)

    async def save(self, error: ErrorRecord) -> None:
        self._by_id[error.id] = error

    async def count_recent(self, source: str, error_type: str, since: datetime) -> int:
        return sum(
            1
            for error in self._by_id.values()
            if error.source == source
            and error.error_type == error_type
            and error.created_at >= since
        )
