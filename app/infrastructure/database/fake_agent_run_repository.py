from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.conversation_id import ConversationId


class FakeAgentRunRepository:
    """In-memory fake implementing `AgentRunRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, AgentRun] = {}

    async def get_by_id(self, agent_run_id: str) -> AgentRun | None:
        return self._by_id.get(agent_run_id)

    async def save(self, agent_run: AgentRun) -> None:
        self._by_id[agent_run.id] = agent_run

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[AgentRun]:
        matches = [
            run for run in self._by_id.values() if run.conversation_id == conversation_id
        ]
        return sorted(matches, key=lambda r: r.started_at, reverse=True)

    async def get_latest_by_conversation_id(
        self, conversation_id: ConversationId
    ) -> AgentRun | None:
        runs = await self.get_by_conversation_id(conversation_id)
        return runs[0] if runs else None

    def all(self) -> list[AgentRun]:
        """Test/dev introspection helper — not part of the `AgentRunRepository` Protocol."""
        return list(self._by_id.values())
