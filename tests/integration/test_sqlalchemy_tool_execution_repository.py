from datetime import UTC, datetime, timedelta

from app.domain.entities.tool_execution import COMPLETED, FAILED, ToolExecution
from app.infrastructure.database.repositories.tool_execution_repository import (
    SqlAlchemyToolExecutionRepository,
)


def _tool_execution(agent_run_id: str, tool_execution_id: str, status: str):
    return ToolExecution(
        id=tool_execution_id,
        agent_run_id=agent_run_id,
        node_execution_id=None,
        tool_name="SearchAvailabilityTool",
        provider="dentalink",
        operation="search_availability",
        request_summary="specialty_id=cleaning",
        response_summary="3 slots" if status == COMPLETED else None,
        status=status,
        http_status="200" if status == COMPLETED else "timeout",
        duration_ms=250,
        error_id=None,
        created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
    )


async def test_save_then_get_by_id_round_trips(db_session, agent_run_id):
    repository = SqlAlchemyToolExecutionRepository(db_session)
    tool_execution = _tool_execution(agent_run_id, "te-1", COMPLETED)

    await repository.save(tool_execution)
    fetched = await repository.get_by_id("te-1")

    assert fetched is not None
    assert fetched.provider == "dentalink"
    assert fetched.status == COMPLETED


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyToolExecutionRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_get_by_agent_run_id_returns_only_matching_executions(db_session, agent_run_id):
    repository = SqlAlchemyToolExecutionRepository(db_session)
    await repository.save(_tool_execution(agent_run_id, "te-2", COMPLETED))
    await repository.save(_tool_execution(agent_run_id, "te-3", FAILED))

    executions = await repository.get_by_agent_run_id(agent_run_id)

    assert {execution.id for execution in executions} == {"te-2", "te-3"}


async def test_list_completed_evidence_filters_joins_conversation_and_orders(
    db_session, agent_run_id, conversation_id
):
    repository = SqlAlchemyToolExecutionRepository(db_session)
    base = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    seeds = [
        ("e-create", "CreateAppointmentTool", "create_appointment", COMPLETED, 0),
        ("e-cancel", "CancelAppointmentTool", "cancel_appointment", COMPLETED, 10),
        ("e-failed", "CreateAppointmentTool", "create_appointment", FAILED, 5),
        ("e-other", "SearchAvailabilityTool", "search_availability", COMPLETED, 5),
        ("e-late", "CreateAppointmentTool", "create_appointment", COMPLETED, 600),
    ]
    for id_, tool_name, operation, status, minutes in seeds:
        execution = _tool_execution(agent_run_id, id_, status)
        execution.tool_name = tool_name
        execution.operation = operation
        execution.created_at = base + timedelta(minutes=minutes)
        await repository.save(execution)

    rows = await repository.list_completed_evidence(
        ["create_appointment", "cancel_appointment"], base, base + timedelta(hours=1), 10
    )
    limited = await repository.list_completed_evidence(
        ["create_appointment", "cancel_appointment"], base, base + timedelta(hours=1), 1
    )

    assert [(row.operation, row.tool_name) for row in rows] == [
        ("cancel_appointment", "CancelAppointmentTool"),
        ("create_appointment", "CreateAppointmentTool"),
    ]
    assert {row.conversation_id for row in rows} == {conversation_id}
    assert all(row.status == COMPLETED for row in rows)
    assert [row.operation for row in limited] == ["cancel_appointment"]
