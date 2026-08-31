from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.error_record import ErrorRecord
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class ErrorRepository(Protocol):
    """Port to durable storage for errors (PRD.md §42)."""

    async def save(self, error: ErrorRecord) -> None: ...

    async def get_by_id(self, error_id: str) -> ErrorRecord | None: ...

    async def list_recent(self, limit: int = 50) -> list[ErrorRecord]:
        """Lists the `limit` most recent errors, newest first (PRD.md §44)."""
        ...

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[ErrorRecord]:
        """Lists every error tied to a conversation (PRD.md §44.1/§44.2)."""
        ...

    async def count_recent(self, source: str, error_type: str, since: datetime) -> int:
        """Counts errors of this `source`+`error_type` since `since`.

        The "aislado" vs "repetido" distinction PRD.md §46's severity
        examples draw (e.g. "dentalink_timeout aislado" = WARNING vs
        "dentalink_timeout repetido" = ERROR) is decided from this count —
        `errors` has no `operation` column (unlike `incidents`, PRD.md
        §49), so this only ever groups by source+error_type.
        """
        ...
