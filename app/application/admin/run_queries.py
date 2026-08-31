from dataclasses import dataclass

from app.domain.entities.agent_run import AgentRun
from app.domain.entities.node_execution import NodeExecution
from app.domain.entities.tool_execution import ToolExecution
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository


@dataclass
class AgentRunDetail:
    """Backing data for `/admin/runs/{id}` (PRD.md §44's third route)."""

    agent_run: AgentRun
    node_executions: list[NodeExecution]
    tool_executions: list[ToolExecution]


class RunQueryService:
    """Read-only query backing `/admin/runs/{id}`."""

    def __init__(
        self,
        agent_runs: AgentRunRepository,
        node_executions: NodeExecutionRepository,
        tool_executions: ToolExecutionRepository,
    ) -> None:
        self._agent_runs = agent_runs
        self._node_executions = node_executions
        self._tool_executions = tool_executions

    async def get_run_detail(self, agent_run_id: str) -> AgentRunDetail | None:
        agent_run = await self._agent_runs.get_by_id(agent_run_id)
        if agent_run is None:
            return None

        return AgentRunDetail(
            agent_run=agent_run,
            node_executions=await self._node_executions.get_by_agent_run_id(agent_run_id),
            tool_executions=await self._tool_executions.get_by_agent_run_id(agent_run_id),
        )
