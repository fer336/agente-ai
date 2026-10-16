from datetime import UTC, datetime

import pytest

from app.domain.repositories.tool_execution_repository import ToolExecutionRepository
from app.infrastructure.database.fake_tool_execution_repository import (
    FakeToolExecutionRepository,
)
from tests.fixtures.gateways import make_agent_run_repository, make_tool_execution_repository
from tests.fixtures.seed_objects import make_agent_run, make_tool_execution


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_tool_execution_repository()
    tool_execution = make_tool_execution(id_="te-1")

    await repository.save(tool_execution)
    fetched = await repository.get_by_id("te-1")

    assert fetched is tool_execution


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_tool_execution_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_by_agent_run_id_returns_only_matching_executions_in_order():
    repository = make_tool_execution_repository()
    await repository.save(
        make_tool_execution(
            id_="te-2", agent_run_id="run-1", created_at=datetime(2026, 8, 11, 9, 1, tzinfo=UTC)
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-1", agent_run_id="run-1", created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
        )
    )
    await repository.save(make_tool_execution(id_="te-3", agent_run_id="run-2"))

    executions = await repository.get_by_agent_run_id("run-1")

    assert [execution.id for execution in executions] == ["te-1", "te-2"]


def test_fake_tool_execution_repository_satisfies_protocol():
    assert isinstance(FakeToolExecutionRepository(), ToolExecutionRepository)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 10, hour, minute, tzinfo=UTC)


async def _repository_with_runs():
    agent_runs = make_agent_run_repository()
    await agent_runs.save(make_agent_run(id_="run-1", conversation_id="conv-1"))
    await agent_runs.save(make_agent_run(id_="run-2", conversation_id="conv-2"))
    return FakeToolExecutionRepository(agent_runs=agent_runs)


@pytest.mark.asyncio
async def test_list_completed_evidence_filters_operation_status_period_and_joins_conversation():
    repository = await _repository_with_runs()
    ok = dict(provider="dentalink", status="completed")
    await repository.save(
        make_tool_execution(
            id_="te-in",
            agent_run_id="run-1",
            tool_name="CreateAppointmentTool",
            operation="create_appointment",
            response_summary="appointment_id=9",
            created_at=_at(10),
            **ok,
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-cancel",
            agent_run_id="run-2",
            operation="cancel_appointment",
            created_at=_at(11),
            **ok,
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-failed",
            agent_run_id="run-1",
            operation="create_appointment",
            created_at=_at(10),
            provider="dentalink",
            status="failed",
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-other-op",
            agent_run_id="run-1",
            operation="search_availability",
            created_at=_at(10),
            **ok,
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-late",
            agent_run_id="run-1",
            operation="create_appointment",
            created_at=_at(20),
            **ok,
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-orphan",
            agent_run_id="missing-run",
            operation="create_appointment",
            created_at=_at(10),
            **ok,
        )
    )

    rows = await repository.list_completed_evidence(
        {"create_appointment", "cancel_appointment"}, _at(8), _at(18), 50
    )

    assert [(row.operation, row.conversation_id) for row in rows] == [
        ("cancel_appointment", "conv-2"),
        ("create_appointment", "conv-1"),
    ]
    created = rows[1]
    assert created.tool_name == "CreateAppointmentTool"
    assert created.status == "completed"
    assert created.created_at == _at(10)
    assert created.response_summary == "appointment_id=9"


@pytest.mark.asyncio
async def test_list_completed_evidence_orders_newest_first_and_applies_limit():
    repository = await _repository_with_runs()
    for id_, hour in (("a", 9), ("b", 12), ("c", 10)):
        await repository.save(
            make_tool_execution(
                id_=id_, agent_run_id="run-1", operation="create_appointment", created_at=_at(hour)
            )
        )

    rows = await repository.list_completed_evidence({"create_appointment"}, _at(0), _at(23), 2)

    assert [row.created_at.hour for row in rows] == [12, 10]
