from collections.abc import Callable, Collection
from datetime import UTC, datetime

from app.domain.entities.pending_action import PendingAction
from app.domain.repositories.pending_action_repository import ConfirmedPendingAction
from app.domain.value_objects.conversation_id import ConversationId


class FakePendingActionRepository:
    """In-memory fake implementing `PendingActionRepository` for local dev and tests."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._by_id: dict[str, PendingAction] = {}
        self._confirmed_at: dict[str, datetime] = {}
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    async def get_by_id(self, pending_action_id: str) -> PendingAction | None:
        return self._by_id.get(pending_action_id)

    async def save(self, pending_action: PendingAction) -> None:
        self._by_id[pending_action.id] = pending_action

    async def get_pending_for_conversation(
        self, conversation_id: ConversationId
    ) -> list[PendingAction]:
        return [
            pending_action
            for pending_action in self._by_id.values()
            if str(pending_action.conversation_id) == str(conversation_id)
            and pending_action.status == "pending"
        ]

    async def get_pending_for_conversation_generation(
        self, conversation_id: ConversationId, workflow_generation: int
    ) -> list[PendingAction]:
        return [
            pending_action
            for pending_action in self._by_id.values()
            if str(pending_action.conversation_id) == str(conversation_id)
            and pending_action.workflow_generation == workflow_generation
            and pending_action.status == "pending"
        ]

    async def mark_expired_if_pending(self, pending_action_id: str) -> bool:
        pending_action = self._by_id.get(pending_action_id)
        if pending_action is None or pending_action.status != "pending":
            return False
        pending_action.status = "expired"
        return True

    async def mark_confirmed_if_pending(self, pending_action_id: str) -> bool:
        pending_action = self._by_id.get(pending_action_id)
        if pending_action is None or pending_action.status != "pending":
            return False
        pending_action.status = "confirmed"
        self._confirmed_at[pending_action_id] = self._clock()
        return True

    async def list_confirmed_between(
        self,
        action_types: Collection[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ConfirmedPendingAction]:
        rows = [
            ConfirmedPendingAction(
                id=action.id,
                conversation_id=str(action.conversation_id),
                action_type=action.action_type,
                payload=action.payload,
                confirmed_at=self._confirmed_at[action.id],
            )
            for action in self._by_id.values()
            if action.status == "confirmed"
            and action.action_type in action_types
            and action.id in self._confirmed_at
            and start <= self._confirmed_at[action.id] < end
        ]
        rows.sort(key=lambda row: row.confirmed_at, reverse=True)
        return rows[:limit]

    def set_confirmed_at(self, pending_action_id: str, confirmed_at: datetime) -> None:
        """Test/dev helper — not part of the Protocols; seeds a row's `confirmed_at`."""
        self._confirmed_at[pending_action_id] = confirmed_at
