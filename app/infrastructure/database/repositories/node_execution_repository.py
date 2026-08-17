from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.node_execution import NodeExecution
from app.infrastructure.database.models.node_execution import NodeExecutionModel


class SqlAlchemyNodeExecutionRepository:
    """`NodeExecutionRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, node_execution_id: str) -> NodeExecution | None:
        model = await self._session.get(NodeExecutionModel, node_execution_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, node_execution: NodeExecution) -> None:
        model = await self._session.get(NodeExecutionModel, node_execution.id)
        if model is None:
            model = NodeExecutionModel(id=node_execution.id)
            self._session.add(model)

        model.agent_run_id = node_execution.agent_run_id
        model.node_name = node_execution.node_name
        model.started_at = node_execution.started_at
        model.finished_at = node_execution.finished_at
        model.status = node_execution.status
        model.input_summary = node_execution.input_summary
        model.output_summary = node_execution.output_summary
        model.duration_ms = node_execution.duration_ms
        model.error_id = node_execution.error_id
        await self._session.flush()

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[NodeExecution]:
        result = await self._session.execute(
            select(NodeExecutionModel)
            .where(NodeExecutionModel.agent_run_id == agent_run_id)
            .order_by(NodeExecutionModel.started_at)
        )
        return [_to_entity(model) for model in result.scalars()]


def _to_entity(model: NodeExecutionModel) -> NodeExecution:
    return NodeExecution(
        id=model.id,
        agent_run_id=model.agent_run_id,
        node_name=model.node_name,
        started_at=model.started_at,
        finished_at=model.finished_at,
        status=model.status,
        input_summary=model.input_summary,
        output_summary=model.output_summary,
        duration_ms=model.duration_ms,
        error_id=model.error_id,
    )
