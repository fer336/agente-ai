from typing import Protocol, runtime_checkable

from app.domain.entities.tool_execution import ToolExecution


@runtime_checkable
class ToolExecutionRepository(Protocol):
    """Port to durable storage for tool executions (PRD.md §41)."""

    async def save(self, tool_execution: ToolExecution) -> None: ...

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None: ...

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[ToolExecution]: ...
