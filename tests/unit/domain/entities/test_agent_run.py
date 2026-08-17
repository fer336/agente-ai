from datetime import UTC, datetime

from app.domain.entities.agent_run import COMPLETED, RUNNING, AgentRun
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_agent_run_with_all_fields():
    agent_run = AgentRun(
        id="run-1",
        conversation_id=ConversationId(value="conv-1"),
        message_id="msg-1",
        trace_id="trace-1",
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        finished_at=None,
        status=RUNNING,
        current_node="resolve_interaction",
        error_id=None,
    )

    assert agent_run.status == RUNNING
    assert agent_run.current_node == "resolve_interaction"
    assert agent_run.finished_at is None


def test_agent_runs_with_different_status_are_not_equal():
    started_at = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    base_kwargs = {
        "id": "run-2",
        "conversation_id": ConversationId(value="conv-2"),
        "message_id": "msg-2",
        "trace_id": "trace-2",
        "prompt_version": "agent-system-v0.1.0",
        "model": "gpt-4o-mini",
        "started_at": started_at,
        "current_node": None,
        "error_id": None,
    }
    first = AgentRun(**base_kwargs, finished_at=None, status=RUNNING)
    second = AgentRun(**base_kwargs, finished_at=started_at, status=COMPLETED)

    assert first != second
