from app.domain.entities.tool_execution import ToolExecution


def test_creates_tool_execution_with_all_fields():
    tool_execution = ToolExecution(
        id="te-1",
        agent_run_id="run-1",
        tool_name="search_availability",
        arguments={"specialty_id": "cleaning"},
        result=None,
        status="running",
    )

    assert tool_execution.tool_name == "search_availability"
    assert tool_execution.result is None
    assert tool_execution.status == "running"


def test_tool_executions_with_different_result_are_not_equal():
    first = ToolExecution(
        id="te-2",
        agent_run_id="run-2",
        tool_name="create_appointment",
        arguments={},
        result=None,
        status="completed",
    )
    second = ToolExecution(
        id="te-2",
        agent_run_id="run-2",
        tool_name="create_appointment",
        arguments={},
        result={"appointment_id": "appt-1"},
        status="completed",
    )

    assert first != second
