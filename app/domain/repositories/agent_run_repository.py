from typing import Protocol, runtime_checkable

from app.domain.entities.agent_run import AgentRun


@runtime_checkable
class AgentRunRepository(Protocol):
    """Port to durable storage for agent runs (PRD.md §39)."""

    async def save(self, agent_run: AgentRun) -> None: ...

    async def get_by_id(self, agent_run_id: str) -> AgentRun | None: ...
