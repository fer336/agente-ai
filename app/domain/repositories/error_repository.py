from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.error_record import ErrorRecord


@runtime_checkable
class ErrorRepository(Protocol):
    """Port to durable storage for errors (PRD.md §42)."""

    async def save(self, error: ErrorRecord) -> None: ...

    async def get_by_id(self, error_id: str) -> ErrorRecord | None: ...

    async def count_recent(self, source: str, error_type: str, since: datetime) -> int:
        """Counts errors of this `source`+`error_type` since `since`.

        The "aislado" vs "repetido" distinction PRD.md §46's severity
        examples draw (e.g. "dentalink_timeout aislado" = WARNING vs
        "dentalink_timeout repetido" = ERROR) is decided from this count —
        `errors` has no `operation` column (unlike `incidents`, PRD.md
        §49), so this only ever groups by source+error_type.
        """
        ...
