from typing import Protocol, runtime_checkable

from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class PendingActionRepository(Protocol):
    """Port to durable storage for pending actions."""

    async def get_by_id(self, pending_action_id: str) -> PendingAction | None: ...

    async def save(self, pending_action: PendingAction) -> None: ...

    async def get_pending_for_conversation(
        self, conversation_id: ConversationId
    ) -> list[PendingAction]: ...

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
