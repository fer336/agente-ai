import pytest

from app.agent.nodes.error_handling import with_error_handling
from app.domain.entities.node_execution import COMPLETED, FAILED, RUNNING
from app.infrastructure.observability.trace_context import get_trace_context
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import (
    make_error_repository,
    make_error_service,
    make_node_execution_repository,
    make_tool_execution_repository,
)


@pytest.mark.asyncio
async def test_wrapped_node_returns_the_inner_nodes_result_when_it_succeeds():
    async def inner(state):
        return {"response_text": "ok"}

    wrapped = with_error_handling(
        "some_node",
        inner,
        make_node_execution_repository(),
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    result = await wrapped(make_agent_state())

    assert result == {"response_text": "ok"}


@pytest.mark.asyncio
async def test_wrapped_node_catches_exceptions_and_sets_the_error_field():
    async def inner(state):
        raise RuntimeError("boom")

    wrapped = with_error_handling(
        "some_node",
        inner,
        make_node_execution_repository(),
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    result = await wrapped(make_agent_state())

    assert result == {"error": "some_node"}


@pytest.mark.asyncio
async def test_records_a_completed_node_execution_on_success():
    async def inner(state):
        return {"response_text": "ok", "requires_handoff": False}

    repository = make_node_execution_repository()
    wrapped = with_error_handling(
        "resolve_interaction",
        inner,
        repository,
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    await wrapped(make_agent_state())

    executions = await repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].node_name == "resolve_interaction"
    assert executions[0].status == COMPLETED
    assert executions[0].error_id is None
    assert "response_len=2" in executions[0].output_summary


@pytest.mark.asyncio
async def test_records_a_failed_node_execution_and_reports_it_on_exception():
    async def inner(state):
        raise RuntimeError("boom")

    node_execution_repository = make_node_execution_repository()
    error_repository = make_error_repository()
    wrapped = with_error_handling(
        "search_availability",
        inner,
        node_execution_repository,
        "run-1",
        make_tool_execution_repository(),
        make_error_service(error_repository),
    )

    await wrapped(make_agent_state())

    executions = await node_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].node_name == "search_availability"
    assert executions[0].status == FAILED
    assert executions[0].error_id is not None
    error = await error_repository.get_by_id(executions[0].error_id)
    assert error is not None
    assert error.source == "langgraph"
    assert error.error_type == "unexpected_exception"
    assert error.severity == "CRITICAL"
    assert error.agent_run_id == "run-1"


@pytest.mark.asyncio
async def test_input_summary_never_includes_the_raw_user_message():
    async def inner(state):
        return {"response_text": "ok"}

    repository = make_node_execution_repository()
    wrapped = with_error_handling(
        "awaiting_identification",
        inner,
        repository,
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    await wrapped(make_agent_state(user_message="Juan Perez, 30123456"))

    executions = await repository.get_by_agent_run_id("run-1")
    assert "30123456" not in executions[0].input_summary
    assert "Juan Perez" not in executions[0].input_summary


@pytest.mark.asyncio
async def test_a_running_placeholder_exists_before_the_node_body_runs():
    # Regression test: `traced_call` (invoked from inside a node) saves a
    # ToolExecution row referencing this node_execution_id the moment a
    # tool call fails — real Postgres enforces a foreign key from
    # tool_executions to node_executions, so that save fails outright
    # unless a node_executions row already exists by then. Confirmed live
    # in production: a classify_intent failure produced a
    # ForeignKeyViolationError which then poisoned the session for the
    # real error write, silently losing the original exception.
    seen_statuses: list[str | None] = []

    async def inner(state):
        # Exactly one row must already exist for this agent run — written
        # by `with_error_handling` before calling this function — with a
        # placeholder RUNNING status.
        rows = await repository.get_by_agent_run_id("run-1")
        seen_statuses.append(rows[0].status if rows else None)
        return {"response_text": "ok"}

    repository = make_node_execution_repository()
    wrapped = with_error_handling(
        "resolve_interaction",
        inner,
        repository,
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    await wrapped(make_agent_state())

    assert seen_statuses == [RUNNING]
    # And the placeholder is overwritten, not duplicated, by the final write.
    final_rows = await repository.get_by_agent_run_id("run-1")
    assert len(final_rows) == 1
    assert final_rows[0].status == COMPLETED


@pytest.mark.asyncio
async def test_opens_a_trace_context_matching_the_recorded_node_execution():
    seen = {}

    async def inner(state):
        context = get_trace_context()
        seen["agent_run_id"] = context.agent_run_id if context else None
        seen["node_execution_id"] = context.node_execution_id if context else None
        return {"response_text": "ok"}

    repository = make_node_execution_repository()
    wrapped = with_error_handling(
        "appointment",
        inner,
        repository,
        "run-1",
        make_tool_execution_repository(),
        make_error_service(),
    )

    await wrapped(make_agent_state())

    executions = await repository.get_by_agent_run_id("run-1")
    assert seen["agent_run_id"] == "run-1"
    assert seen["node_execution_id"] == executions[0].id
    assert get_trace_context() is None
