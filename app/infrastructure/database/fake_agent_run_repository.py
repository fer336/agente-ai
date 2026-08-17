from app.domain.entities.agent_run import AgentRun


class FakeAgentRunRepository:
    """In-memory fake implementing `AgentRunRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, AgentRun] = {}

    async def get_by_id(self, agent_run_id: str) -> AgentRun | None:
        return self._by_id.get(agent_run_id)

    async def save(self, agent_run: AgentRun) -> None:
        self._by_id[agent_run.id] = agent_run

    def all(self) -> list[AgentRun]:
        """Test/dev introspection helper — not part of the `AgentRunRepository` Protocol."""
        return list(self._by_id.values())
