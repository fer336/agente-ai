from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.agent_run import AgentRunModel


class SqlAlchemyAgentRunRepository:
    """`AgentRunRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, agent_run_id: str) -> AgentRun | None:
        model = await self._session.get(AgentRunModel, agent_run_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, agent_run: AgentRun) -> None:
        model = await self._session.get(AgentRunModel, agent_run.id)
        if model is None:
            model = AgentRunModel(id=agent_run.id)
            self._session.add(model)

        model.conversation_id = str(agent_run.conversation_id)
        model.message_id = agent_run.message_id
        model.trace_id = agent_run.trace_id
        model.prompt_version = agent_run.prompt_version
        model.model = agent_run.model
        model.started_at = agent_run.started_at
        model.finished_at = agent_run.finished_at
        model.status = agent_run.status
        model.current_node = agent_run.current_node
        model.error_id = agent_run.error_id
        await self._session.flush()


def _to_entity(model: AgentRunModel) -> AgentRun:
    return AgentRun(
        id=model.id,
        conversation_id=ConversationId(value=model.conversation_id),
        message_id=model.message_id,
        trace_id=model.trace_id,
        prompt_version=model.prompt_version,
        model=model.model,
        started_at=model.started_at,
        finished_at=model.finished_at,
        status=model.status,
        current_node=model.current_node,
        error_id=model.error_id,
    )
