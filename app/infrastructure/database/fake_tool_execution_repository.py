from collections.abc import Collection
from datetime import datetime

from app.domain.entities.tool_execution import COMPLETED, ToolExecution
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionEvidence


class FakeToolExecutionRepository:
    """In-memory fake implementing `ToolExecutionRepository` for local dev and tests."""

    def __init__(self, agent_runs: AgentRunRepository | None = None) -> None:
        self._by_id: dict[str, ToolExecution] = {}
        # Needed only to emulate the `agent_runs` join of `list_completed_evidence`.
        self._agent_runs = agent_runs

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None:
        return self._by_id.get(tool_execution_id)

    async def save(self, tool_execution: ToolExecution) -> None:
        self._by_id[tool_execution.id] = tool_execution

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[ToolExecution]:
        matches = [te for te in self._by_id.values() if te.agent_run_id == agent_run_id]
        matches.sort(key=lambda te: te.created_at)
        return matches

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        self._by_id = {
            id_: te for id_, te in self._by_id.items() if te.agent_run_id != agent_run_id
        }

    async def list_completed_evidence(
        self,
        operations: Collection[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ToolExecutionEvidence]:
        rows: list[ToolExecutionEvidence] = []
        if self._agent_runs is None:
            return rows
        for te in self._by_id.values():
            if (
                te.status != COMPLETED
                or te.operation not in operations
                or not start <= te.created_at < end
            ):
                continue
            run = await self._agent_runs.get_by_id(te.agent_run_id)
            if run is None:  # SQL inner join drops executions without a run
                continue
            rows.append(
                ToolExecutionEvidence(
                    tool_name=te.tool_name,
                    operation=te.operation,
                    status=te.status,
                    created_at=te.created_at,
                    response_summary=te.response_summary,
                    conversation_id=str(run.conversation_id),
                )
            )
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[:limit]
