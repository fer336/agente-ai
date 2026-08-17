from datetime import UTC, datetime

from app.domain.entities.node_execution import COMPLETED, FAILED, NodeExecution
from app.infrastructure.database.repositories.node_execution_repository import (
    SqlAlchemyNodeExecutionRepository,
)


def _node_execution(agent_run_id: str, node_execution_id: str, node_name: str, status: str):
    now = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    return NodeExecution(
        id=node_execution_id,
        agent_run_id=agent_run_id,
        node_name=node_name,
        started_at=now,
        finished_at=now,
        status=status,
        input_summary="intent=appointment",
        output_summary="stage=awaiting_identification",
        duration_ms=42,
        error_id=None,
    )


async def test_save_then_get_by_id_round_trips(db_session, agent_run_id):
    repository = SqlAlchemyNodeExecutionRepository(db_session)
    node_execution = _node_execution(agent_run_id, "ne-1", "resolve_interaction", COMPLETED)

    await repository.save(node_execution)
    fetched = await repository.get_by_id("ne-1")

    assert fetched is not None
    assert fetched.node_name == "resolve_interaction"
    assert fetched.status == COMPLETED


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyNodeExecutionRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_get_by_agent_run_id_returns_only_matching_executions(db_session, agent_run_id):
    repository = SqlAlchemyNodeExecutionRepository(db_session)
    await repository.save(
        _node_execution(agent_run_id, "ne-2", "resolve_interaction", COMPLETED)
    )
    await repository.save(_node_execution(agent_run_id, "ne-3", "appointment", FAILED))

    executions = await repository.get_by_agent_run_id(agent_run_id)

    assert {execution.id for execution in executions} == {"ne-2", "ne-3"}
