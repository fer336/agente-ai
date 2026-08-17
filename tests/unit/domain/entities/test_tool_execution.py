from datetime import UTC, datetime

from app.domain.entities.tool_execution import COMPLETED, FAILED, ToolExecution


def test_creates_tool_execution_with_all_fields():
    tool_execution = ToolExecution(
        id="te-1",
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_name="SearchAvailabilityTool",
        provider="dentalink",
        operation="search_availability",
        request_summary="specialty_id=cleaning",
        response_summary="3 slots",
        status=COMPLETED,
        http_status="200",
        duration_ms=250,
        error_id=None,
        created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
    )

    assert tool_execution.provider == "dentalink"
    assert tool_execution.operation == "search_availability"
    assert tool_execution.status == COMPLETED


def test_tool_executions_with_different_status_are_not_equal():
    created_at = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    base_kwargs = {
        "id": "te-2",
        "agent_run_id": "run-2",
        "node_execution_id": None,
        "tool_name": "SearchAvailabilityTool",
        "provider": "dentalink",
        "operation": "search_availability",
        "request_summary": "",
        "duration_ms": 15023,
        "created_at": created_at,
    }
    first = ToolExecution(
        **base_kwargs,
        response_summary="3 slots",
        status=COMPLETED,
        http_status="200",
        error_id=None,
    )
    second = ToolExecution(
        **base_kwargs, response_summary=None, status=FAILED, http_status="timeout", error_id="err-1"
    )

    assert first != second
