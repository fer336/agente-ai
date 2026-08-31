from typing import Protocol, runtime_checkable

from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class AgentRunRepository(Protocol):
    """Port to durable storage for agent runs (PRD.md §39)."""

    async def save(self, agent_run: AgentRun) -> None: ...

    async def get_by_id(self, agent_run_id: str) -> AgentRun | None: ...

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[AgentRun]:
        """Lists every run for a conversation, newest first (PRD.md §44.2)."""
        ...

    async def get_latest_by_conversation_id(
        self, conversation_id: ConversationId
    ) -> AgentRun | None:
        """Most recent run for a conversation — backs the `/admin/conversations`
        listing's "Resultado" column (PRD.md §44.1), which needs only the
        latest run's outcome, not the full history `get_by_conversation_id`
        returns.
        """
        ...
