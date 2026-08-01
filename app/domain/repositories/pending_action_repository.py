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
