from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.conversation_id import ConversationId


@dataclass(frozen=True)
class ConfirmedPendingAction:
    """Read model of a confirmed `pending_actions` row for admin KPIs."""

    id: str
    conversation_id: str
    action_type: str
    payload: dict[str, object]
    confirmed_at: datetime


@runtime_checkable
class ConfirmedActionReader(Protocol):
    """Read-only port for KPI queries over confirmed pending actions.

    Kept apart from `PendingActionRepository` so the write-side port (and its
    conformance test) stay untouched; the SQL and fake repositories implement both.
    """

    async def list_confirmed_between(
        self,
        action_types: Collection[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ConfirmedPendingAction]:
        """Rows with `status == 'confirmed'`, `action_type` in the set and
        `start <= confirmed_at < end`, newest first, at most `limit` rows."""
        ...


@runtime_checkable
class PendingActionRepository(Protocol):
    """Port to durable storage for pending actions."""

    async def get_by_id(self, pending_action_id: str) -> PendingAction | None: ...

    async def save(self, pending_action: PendingAction) -> None: ...

    async def get_pending_for_conversation(
        self, conversation_id: ConversationId
    ) -> list[PendingAction]: ...

    async def get_pending_for_conversation_generation(
        self, conversation_id: ConversationId, workflow_generation: int
    ) -> list[PendingAction]:
        """Lists still-pending actions bound to one workflow generation."""
        ...

    async def mark_expired_if_pending(self, pending_action_id: str) -> bool:
        """Atomically transitions `pending` -> `expired`.

        Returns True if this call performed the transition, False if the
        row was no longer `pending` (e.g. a concurrent confirmation already
        moved it to `confirmed`) — the `WHERE status = 'pending'` SQL guard
        that gives mutual exclusion between a follow-up expiration and a
        same-moment confirmation (PRD.md §16.1/§16.3: "Si una confirmación y
        el vencimiento ocurren simultáneamente, solamente una transición
        podrá ganar").
        """
        ...

    async def mark_confirmed_if_pending(self, pending_action_id: str) -> bool:
        """Atomically transitions `pending` -> `confirmed`.

        Symmetric to `mark_expired_if_pending` above — same `WHERE status =
        'pending'` guard, the other side of PRD.md §16.3's race. Returns
        True if this call performed the transition, False if the row was
        no longer `pending` (e.g. the expiration follow-up already won).
        """
        ...
