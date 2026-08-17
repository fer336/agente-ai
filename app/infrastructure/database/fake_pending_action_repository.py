from app.domain.entities.pending_action import PendingAction
from app.domain.value_objects.conversation_id import ConversationId


class FakePendingActionRepository:
    """In-memory fake implementing `PendingActionRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, PendingAction] = {}

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
        return True
