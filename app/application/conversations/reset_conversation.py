from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.entities.conversation import Conversation
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.error_repository import ErrorRepository
from app.domain.repositories.message_repository import MessageRepository
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.redis.debounce import DebounceTracker

#: PRD.md §23's default — the state a conversation starts in before any
#: handoff/mode change. Reset always returns to this, never to whatever
#: `mode` the conversation happened to be in before.
_DEFAULT_MODE = "agent"


class ResetConversationUseCase:
    """Admin-only, testing-tool operation (no PRD.md section number — this
    session's own brief): wipes one conversation's raw message history,
    its `agent_runs`/`node_executions`/`tool_executions`/`errors`
    observability trail, compacted contact memory, LangGraph checkpoint
    thread, `mode`/`input_state`, and pending debounce window — so a real
    WhatsApp number can be re-tested from a clean slate during
    development.

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
        agent_run_repository: AgentRunRepository,
        node_execution_repository: NodeExecutionRepository,
        tool_execution_repository: ToolExecutionRepository,
        error_repository: ErrorRepository,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._memory_service = memory_service
        self._checkpointer = checkpointer
        self._debounce_tracker = debounce_tracker
        self._agent_run_repository = agent_run_repository
        self._node_execution_repository = node_execution_repository
        self._tool_execution_repository = tool_execution_repository
        self._error_repository = error_repository
        self._set_conversation_mode = SetConversationModeUseCase(conversation_repository)
        self._set_conversation_input_state = SetConversationInputStateUseCase(
            conversation_repository
        )

    async def execute(self, conversation_id: ConversationId) -> Conversation | None:
        """Returns the refreshed `Conversation`, or `None` if it doesn't exist."""
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            return None

        # Observability rows reference `messages`/`agent_runs` via plain
        # (non-cascading) FKs — deleting messages before these exist
        # violates `agent_runs_message_id_fkey` (confirmed live in
        # production against a conversation with real agent runs), so
        # they must go first, deepest-referencing table first.
        agent_runs = await self._agent_run_repository.get_by_conversation_id(conversation_id)
        for agent_run in agent_runs:
            await self._tool_execution_repository.delete_by_agent_run_id(agent_run.id)
            await self._node_execution_repository.delete_by_agent_run_id(agent_run.id)
        await self._error_repository.delete_by_conversation_id(conversation_id)
        await self._agent_run_repository.delete_by_conversation_id(conversation_id)

        await self._message_repository.delete_by_conversation_id(conversation_id)
        await self._memory_service.reset(conversation.contact_id)
        await self._checkpointer.adelete_thread(str(conversation_id))
        await self._set_conversation_mode.execute(conversation_id, _DEFAULT_MODE)
        await self._set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        await self._debounce_tracker.clear(str(conversation_id))

        return await self._conversation_repository.get_by_id(conversation_id)
