from datetime import UTC, datetime

from app.domain.entities.node_execution import COMPLETED, FAILED, NodeExecution


def test_creates_node_execution_with_all_fields():
    node_execution = NodeExecution(
        id="ne-1",
        agent_run_id="run-1",
        node_name="resolve_interaction",
        started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 8, 11, 9, 0, 1, tzinfo=UTC),
        status=COMPLETED,
        input_summary="intent=appointment",
        output_summary="intent=appointment",
        duration_ms=1000,
        error_id=None,
    )

    assert node_execution.node_name == "resolve_interaction"
    assert node_execution.status == COMPLETED
    assert node_execution.duration_ms == 1000


def test_node_executions_with_different_status_are_not_equal():
    started_at = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    base_kwargs = {
        "id": "ne-2",
        "agent_run_id": "run-2",
        "node_name": "appointment",
        "started_at": started_at,
        "finished_at": started_at,
        "input_summary": "",
        "output_summary": "",
        "duration_ms": 5,
    }
    first = NodeExecution(**base_kwargs, status=COMPLETED, error_id=None)
    second = NodeExecution(**base_kwargs, status=FAILED, error_id="err-1")

    assert first != second
