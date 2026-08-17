from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.scheduled_action import ScheduledAction


@runtime_checkable
class ScheduledActionRepository(Protocol):
    """Port to durable storage for scheduled follow-up/expiration actions."""

    async def get_by_id(self, scheduled_action_id: str) -> ScheduledAction | None: ...

    async def save(self, scheduled_action: ScheduledAction) -> None: ...

    async def get_due(self, now: datetime, limit: int) -> list[ScheduledAction]: ...

    async def get_by_pending_action_id(
        self, pending_action_id: str
    ) -> ScheduledAction | None:
        """Finds the (at most one) `ScheduledAction` tied to a `PendingAction`.

        Needed to cancel the follow-up timeout once the patient confirms,
        rejects, or otherwise resolves the `PendingAction` before its
        `ScheduledAction` fires (PRD.md §16.3's cancellation list).
        """
        ...

    async def transition_status(
        self, scheduled_action_id: str, *, from_status: str, to_status: str
    ) -> bool:
        """Atomically moves status from `from_status` to `to_status`.

        Returns True if this call performed the transition, False if the
        row was no longer in `from_status` (another process already
        transitioned it) — the `WHERE status = :from_status` SQL guard that
        gives mutual exclusion between concurrent workers (PRD.md §16.3,
        §75.9: "Dos workers -> una sola ejecución").
        """
        ...
