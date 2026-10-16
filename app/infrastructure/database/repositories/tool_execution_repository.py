from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.tool_execution import COMPLETED, ToolExecution
from app.domain.repositories.tool_execution_repository import ToolExecutionEvidence
from app.infrastructure.database.models.agent_run import AgentRunModel
from app.infrastructure.database.models.tool_execution import ToolExecutionModel


class SqlAlchemyToolExecutionRepository:
    """`ToolExecutionRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None:
        model = await self._session.get(ToolExecutionModel, tool_execution_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, tool_execution: ToolExecution) -> None:
        model = await self._session.get(ToolExecutionModel, tool_execution.id)
        if model is None:
            model = ToolExecutionModel(id=tool_execution.id)
            self._session.add(model)

        model.agent_run_id = tool_execution.agent_run_id
        model.node_execution_id = tool_execution.node_execution_id
        model.tool_name = tool_execution.tool_name
        model.provider = tool_execution.provider
        model.operation = tool_execution.operation
        model.request_summary = tool_execution.request_summary
        model.response_summary = tool_execution.response_summary
        model.status = tool_execution.status
        model.http_status = tool_execution.http_status
        model.duration_ms = tool_execution.duration_ms
        model.error_id = tool_execution.error_id
        model.created_at = tool_execution.created_at
        await self._session.flush()

    async def get_by_agent_run_id(self, agent_run_id: str) -> list[ToolExecution]:
        result = await self._session.execute(
            select(ToolExecutionModel)
            .where(ToolExecutionModel.agent_run_id == agent_run_id)
            .order_by(ToolExecutionModel.created_at)
        )
        return [_to_entity(model) for model in result.scalars()]

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        result = await self._session.execute(
            select(ToolExecutionModel).where(ToolExecutionModel.agent_run_id == agent_run_id)
        )
        for model in result.scalars().all():
            await self._session.delete(model)
        await self._session.flush()

    async def list_completed_evidence(
        self,
        operations: Collection[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ToolExecutionEvidence]:
        result = await self._session.execute(
            select(
                ToolExecutionModel.tool_name,
                ToolExecutionModel.operation,
                ToolExecutionModel.status,
                ToolExecutionModel.created_at,
                ToolExecutionModel.response_summary,
                AgentRunModel.conversation_id,
            )
            .join(AgentRunModel, AgentRunModel.id == ToolExecutionModel.agent_run_id)
            .where(
                ToolExecutionModel.status == COMPLETED,
                ToolExecutionModel.operation.in_(list(operations)),
                ToolExecutionModel.created_at >= start,
                ToolExecutionModel.created_at < end,
            )
            .order_by(ToolExecutionModel.created_at.desc())
            .limit(limit)
        )
        return [
            ToolExecutionEvidence(
                tool_name=row.tool_name,
                operation=row.operation,
                status=row.status,
                created_at=row.created_at,
                response_summary=row.response_summary,
                conversation_id=row.conversation_id,
            )
            for row in result
        ]


def _to_entity(model: ToolExecutionModel) -> ToolExecution:
    return ToolExecution(
        id=model.id,
        agent_run_id=model.agent_run_id,
        node_execution_id=model.node_execution_id,
        tool_name=model.tool_name,
        provider=model.provider,
        operation=model.operation,
        request_summary=model.request_summary,
        response_summary=model.response_summary,
        status=model.status,
        http_status=model.http_status,
        duration_ms=model.duration_ms,
        error_id=model.error_id,
        created_at=model.created_at,
    )
