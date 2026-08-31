from typing import Protocol, runtime_checkable

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class ConversationRepository(Protocol):
    """Port to durable storage for conversations."""

    async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None: ...

    async def save(self, conversation: Conversation) -> None: ...

    async def list_recent(self, limit: int = 50) -> list[Conversation]:
        """Lists the `limit` most recently created conversations, newest first.

        Backs the admin panel's `/admin/conversations` listing (PRD.md
        §44.1) — no other caller needs this yet.
        """
        ...
