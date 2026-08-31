from datetime import datetime

from app.domain.entities.error_record import ErrorRecord
from app.domain.repositories.error_repository import ErrorRepository


class ErrorQueryService:
    """Read/resolve queries backing `/admin/errors` and `/admin/errors/{id}`
    (PRD.md §44.3). Cross-links to the related conversation/agent run are
    already plain fields on `ErrorRecord` (`conversation_id`, `agent_run_id`)
    — no extra join needed here.
    """

    def __init__(self, errors: ErrorRepository) -> None:
        self._errors = errors

    async def list_errors(self, limit: int = 50) -> list[ErrorRecord]:
        return await self._errors.list_recent(limit=limit)

    async def get_error_detail(self, error_id: str) -> ErrorRecord | None:
        return await self._errors.get_by_id(error_id)

    async def resolve(self, error_id: str, now: datetime) -> ErrorRecord | None:
        """Marks an error resolved (`resolved_at`). `ADMIN_TECHNICAL`-only —
        enforced by the route's `require_role`, not here.

        Returns `None` (no-op) when the error doesn't exist, so the route
        can 404 instead of silently succeeding.
        """
        error = await self._errors.get_by_id(error_id)
        if error is None:
            return None

        error.resolved_at = now
        await self._errors.save(error)
        return error
