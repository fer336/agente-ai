from datetime import UTC, datetime, timedelta

from app.domain.entities.error_record import SEVERITY_WARNING, SOURCE_DENTALINK, ErrorRecord
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.repositories.error_repository import SqlAlchemyErrorRepository


def _error(
    conversation_id: str,
    agent_run_id: str,
    error_id: str,
    error_type: str = "dentalink_timeout",
    created_at=None,
) -> ErrorRecord:
    return ErrorRecord(
        id=error_id,
        trace_id="trace-1",
        conversation_id=ConversationId(value=conversation_id),
        agent_run_id=agent_run_id,
        source=SOURCE_DENTALINK,
        error_type=error_type,
        error_code=None,
        message="Dentalink did not respond in time",
        technical_detail="httpx.ReadTimeout after 15s",
        severity=SEVERITY_WARNING,
        retryable=True,
        created_at=(
            created_at if created_at is not None else datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
        ),
        resolved_at=None,
    )


async def test_save_then_get_by_id_round_trips(db_session, conversation_id, agent_run_id):
    repository = SqlAlchemyErrorRepository(db_session)
    error = _error(conversation_id, agent_run_id, "err-1")

    await repository.save(error)
    fetched = await repository.get_by_id("err-1")

    assert fetched is not None
    assert fetched.error_type == "dentalink_timeout"
    assert fetched.severity == SEVERITY_WARNING


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyErrorRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_count_recent_only_counts_matching_source_and_error_type_since(
    db_session, conversation_id, agent_run_id
):
    repository = SqlAlchemyErrorRepository(db_session)
    now = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    await repository.save(_error(conversation_id, agent_run_id, "err-2", created_at=now))
    await repository.save(
        _error(conversation_id, agent_run_id, "err-3", created_at=now - timedelta(minutes=5))
    )
    await repository.save(
        _error(
            conversation_id,
            agent_run_id,
            "err-4",
            error_type="dentalink_auth_error",
            created_at=now,
        )
    )

    count = await repository.count_recent(
        SOURCE_DENTALINK, "dentalink_timeout", since=now - timedelta(minutes=2)
    )

    assert count == 1
