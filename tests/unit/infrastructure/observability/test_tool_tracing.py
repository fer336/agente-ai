import pytest

from app.domain.entities.tool_execution import COMPLETED, FAILED
from app.infrastructure.observability.tool_tracing import traced_call
from app.infrastructure.observability.trace_context import TraceContext, use_trace_context
from tests.fixtures.gateways import (
    make_error_repository,
    make_error_service,
    make_tool_execution_repository,
)


@pytest.mark.asyncio
async def test_records_a_completed_tool_execution_on_success():
    repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=repository,
        error_service=make_error_service(),
    )

    async def call():
        return [1, 2, 3]

    with use_trace_context(context):
        result = await traced_call(
            tool_name="SearchAvailabilityTool",
            provider="dentalink",
            operation="search_availability",
            request_summary="specialty_id=cleaning",
            call=call,
            response_summary=lambda slots: f"{len(slots)} slots",
        )

    assert result == [1, 2, 3]
    executions = await repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.tool_name == "SearchAvailabilityTool"
    assert execution.provider == "dentalink"
    assert execution.operation == "search_availability"
    assert execution.status == COMPLETED
    assert execution.response_summary == "3 slots"
    assert execution.node_execution_id == "ne-1"
    assert execution.http_status == "200"


@pytest.mark.asyncio
async def test_records_a_failed_tool_execution_and_reraises():
    repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=repository,
        error_service=make_error_service(),
    )

    async def call():
        raise TimeoutError("boom")

    with (
        use_trace_context(context),
        pytest.raises(TimeoutError),
    ):
        await traced_call(
            tool_name="SearchAvailabilityTool",
            provider="dentalink",
            operation="search_availability",
            request_summary="specialty_id=cleaning",
            call=call,
            http_status_of=lambda exc: "timeout",
        )

    executions = await repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].status == FAILED
    assert executions[0].http_status == "timeout"
    assert executions[0].response_summary is None
    # No `error_type_of` was given — nothing to classify, so no ErrorRecord.
    assert executions[0].error_id is None


@pytest.mark.asyncio
async def test_records_a_failed_tool_execution_and_reports_it_when_error_type_of_is_given():
    tool_execution_repository = make_tool_execution_repository()
    error_repository = make_error_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(error_repository),
    )

    async def call():
        raise TimeoutError("boom")

    with use_trace_context(context), pytest.raises(TimeoutError):
        await traced_call(
            tool_name="SearchAvailabilityTool",
            provider="dentalink",
            operation="search_availability",
            request_summary="specialty_id=cleaning",
            call=call,
            error_type_of=lambda exc: "dentalink_timeout",
        )

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert executions[0].error_id is not None
    error = await error_repository.get_by_id(executions[0].error_id)
    assert error is not None
    assert error.error_type == "dentalink_timeout"
    assert error.source == "dentalink"
    assert error.agent_run_id == "run-1"


@pytest.mark.asyncio
async def test_is_a_noop_outside_a_trace_context():
    async def call():
        return "ok"

    result = await traced_call(
        tool_name="SearchAvailabilityTool",
        provider="dentalink",
        operation="search_availability",
        request_summary="specialty_id=cleaning",
        call=call,
    )

    assert result == "ok"


@pytest.mark.asyncio
async def test_never_serializes_the_call_result_without_an_explicit_response_summary():
    repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=repository,
        error_service=make_error_service(),
    )

    class _SensitivePatient:
        def __str__(self):  # pragma: no cover - must never be invoked
            raise AssertionError("must never be stringified into a summary")

    async def call():
        return _SensitivePatient()

    with use_trace_context(context):
        await traced_call(
            tool_name="CreateAppointmentTool",
            provider="dentalink",
            operation="create_appointment",
            request_summary="slot_id=slot-1",
            call=call,
        )

    executions = await repository.get_by_agent_run_id("run-1")
    assert executions[0].response_summary is None
