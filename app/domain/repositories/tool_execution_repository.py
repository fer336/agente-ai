from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.tool_execution import ToolExecution


@dataclass(frozen=True)
class ToolExecutionEvidence:
    """Read model of a completed tool execution plus its conversation (admin KPIs)."""

    tool_name: str
    operation: str
    status: str
    created_at: datetime
    response_summary: str | None
    conversation_id: str


@runtime_checkable
class ToolExecutionRepository(Protocol):
    """Port to durable storage for tool executions (PRD.md §41)."""

    async def save(self, tool_execution: ToolExecution) -> None: ...

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None: ...

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[ToolExecution]: ...

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        """Deletes every tool execution for one run (`ResetConversationUseCase`).

        `tool_executions.node_execution_id` is a plain FK to
        `node_executions.id` — this must run before the node executions
        themselves are deleted.
        """
        ...

    async def list_completed_evidence(
        self,
        operations: Collection[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ToolExecutionEvidence]:
        """Completed executions of `operations` with `start <= created_at < end`,
        newest first, at most `limit` rows, each with the conversation id from
        `agent_runs.conversation_id` (inner join: orphan rows are skipped)."""
        ...
