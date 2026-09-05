from app.domain.entities.node_execution import NodeExecution


class FakeNodeExecutionRepository:
    """In-memory fake implementing `NodeExecutionRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, NodeExecution] = {}

    async def get_by_id(self, node_execution_id: str) -> NodeExecution | None:
        return self._by_id.get(node_execution_id)

    async def save(self, node_execution: NodeExecution) -> None:
        self._by_id[node_execution.id] = node_execution

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[NodeExecution]:
        matches = [ne for ne in self._by_id.values() if ne.agent_run_id == agent_run_id]
        matches.sort(key=lambda ne: ne.started_at)
        return matches

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        self._by_id = {
            id_: ne for id_, ne in self._by_id.items() if ne.agent_run_id != agent_run_id
        }
