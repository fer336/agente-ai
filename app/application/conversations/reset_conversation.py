from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.entities.conversation import Conversation
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.redis.debounce import DebounceTracker

#: PRD.md §23's default — the state a conversation starts in before any
#: handoff/mode change. Reset always returns to this, never to whatever
#: `mode` the conversation happened to be in before.
_DEFAULT_MODE = "agent"


class ResetConversationUseCase:
    """Admin-only, testing-tool operation (no PRD.md section number — this
    session's own brief): wipes one conversation's raw message history,
    compacted contact memory, LangGraph checkpoint thread, `mode`/
    `input_state`, and pending debounce window — so a real WhatsApp number
    can be re-tested from a clean slate during development.

    Irreversibly destructive — NEVER call this against a real patient
    conversation. Distinct from `MemoryService.compact`'s automatic,
    non-destructive production compaction (see that module's own
    docstring): this is a manual reset tool, that is an always-on sweep;
    neither one calls the other.
    """

    def __init__(
        self,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
        memory_service: MemoryService,
        checkpointer: BaseCheckpointSaver[Any],
        debounce_tracker: DebounceTracker,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._memory_service = memory_service
        self._checkpointer = checkpointer
        self._debounce_tracker = debounce_tracker
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(self, conversation_id: ConversationId) -> Conversation | None:
        """Returns the refreshed `Conversation`, or `None` if it doesn't exist."""
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return None

        await self._message_repository.delete_by_conversation_id(conversation_id)
        await self._memory_service.reset(conversation.contact_id)
        await self._checkpointer.adelete_thread(str(conversation_id))
        await self._set_conversation_mode.execute(conversation_id, _DEFAULT_MODE)
        await self._set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        await self._debounce_tracker.clear(str(conversation_id))

        return await self._conversation_repository.get_by_id(conversation_id)
