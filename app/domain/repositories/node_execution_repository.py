from typing import Protocol, runtime_checkable

from app.domain.entities.node_execution import NodeExecution


@runtime_checkable
class NodeExecutionRepository(Protocol):
    """Port to durable storage for node executions (PRD.md §40)."""

    async def save(self, node_execution: NodeExecution) -> None: ...

    async def get_by_id(self, node_execution_id: str) -> NodeExecution | None: ...

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[NodeExecution]: ...

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        """Deletes every node execution for one run (`ResetConversationUseCase`)."""
        ...
