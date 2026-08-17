from app.domain.entities.tool_execution import ToolExecution


class FakeToolExecutionRepository:
    """In-memory fake implementing `ToolExecutionRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, ToolExecution] = {}

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None:
        return self._by_id.get(tool_execution_id)

    async def save(self, tool_execution: ToolExecution) -> None:
        self._by_id[tool_execution.id] = tool_execution

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[ToolExecution]:
        matches = [te for te in self._by_id.values() if te.agent_run_id == agent_run_id]
        matches.sort(key=lambda te: te.created_at)
        return matches
