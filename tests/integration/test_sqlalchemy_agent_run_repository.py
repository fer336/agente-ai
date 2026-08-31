from datetime import UTC, datetime

from app.domain.entities.agent_run import COMPLETED, RUNNING, AgentRun
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)


def _agent_run(
    conversation_id: str, message_id: str, run_id: str, status: str, finished_at=None
) -> AgentRun:
    return AgentRun(
        id=run_id,
        conversation_id=ConversationId(value=conversation_id),
        message_id=message_id,
        trace_id="trace-1",
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        finished_at=finished_at,
        status=status,
        current_node="resolve_interaction",
        error_id=None,
    )


async def test_save_then_get_by_id_round_trips(db_session, conversation_id, message_id):
    repository = SqlAlchemyAgentRunRepository(db_session)
    agent_run = _agent_run(conversation_id, message_id, "run-1", RUNNING)

    await repository.save(agent_run)
    fetched = await repository.get_by_id("run-1")

    assert fetched is not None
    assert fetched.status == RUNNING
    assert fetched.finished_at is None


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyAgentRunRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_save_upserts_the_same_row_by_id(db_session, conversation_id, message_id):
    repository = SqlAlchemyAgentRunRepository(db_session)
    await repository.save(_agent_run(conversation_id, message_id, "run-2", RUNNING))

    finished_at = datetime(2026, 8, 11, 9, 0, 5, tzinfo=UTC)
    await repository.save(
        _agent_run(conversation_id, message_id, "run-2", COMPLETED, finished_at=finished_at)
    )

    fetched = await repository.get_by_id("run-2")
    assert fetched is not None
    assert fetched.status == COMPLETED
    assert fetched.finished_at == finished_at


async def test_get_by_conversation_id_orders_newest_first(db_session, conversation_id, message_id):
    repository = SqlAlchemyAgentRunRepository(db_session)
    earlier = _agent_run(conversation_id, message_id, "run-earlier", COMPLETED)
    later = _agent_run(conversation_id, message_id, "run-later", RUNNING)
    later.started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    await repository.save(earlier)
    await repository.save(later)

    fetched = await repository.get_by_conversation_id(ConversationId(value=conversation_id))

    assert [run.id for run in fetched] == ["run-later", "run-earlier"]


async def test_get_latest_by_conversation_id_returns_none_when_no_runs(db_session):
    repository = SqlAlchemyAgentRunRepository(db_session)

    assert await repository.get_latest_by_conversation_id(ConversationId(value="conv-none")) is None


async def test_get_latest_by_conversation_id_returns_the_most_recent_run(
    db_session, conversation_id, message_id
):
    repository = SqlAlchemyAgentRunRepository(db_session)
    earlier = _agent_run(conversation_id, message_id, "run-a", COMPLETED)
    later = _agent_run(conversation_id, message_id, "run-b", RUNNING)
    later.started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    await repository.save(earlier)
    await repository.save(later)

    latest = await repository.get_latest_by_conversation_id(ConversationId(value=conversation_id))

    assert latest is not None
    assert latest.id == "run-b"
