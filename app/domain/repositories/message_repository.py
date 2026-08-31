from typing import Protocol, runtime_checkable

from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId


@runtime_checkable
class MessageRepository(Protocol):
    """Port to durable storage for messages."""

    async def exists_by_external_id(self, external_message_id: ExternalMessageId) -> bool: ...

    async def save(self, message: Message) -> None: ...

    async def get_by_id(self, message_id: str) -> Message | None: ...

    async def update(self, message: Message) -> None:
        """Persists changes to an ALREADY-EXISTING message row.

        Distinct from `save` (which the codebase's other call sites use as
        an insert-only "first write" for a brand-new message) — this is the
        audio pipeline's "second write": `TranscribeAudioUseCase` loads a
        message via `get_by_id`, fills in `text`/`transcription_*`, and
        calls `update` once it has a transcript or a terminal failure.
        """
        ...

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[Message]:
        """Lists every message in a conversation, oldest first.

        Backs the admin panel's conversation detail view (PRD.md §44.2).
        """
        ...
