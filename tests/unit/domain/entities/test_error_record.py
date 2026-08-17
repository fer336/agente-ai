from datetime import UTC, datetime

from app.domain.entities.error_record import (
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SOURCE_DENTALINK,
    ErrorRecord,
)
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_error_record_with_all_fields():
    error = ErrorRecord(
        id="err-1",
        trace_id="trace-1",
        conversation_id=ConversationId(value="conv-1"),
        agent_run_id="run-1",
        source=SOURCE_DENTALINK,
        error_type="dentalink_timeout",
        error_code=None,
        message="Dentalink did not respond in time",
        technical_detail="httpx.ReadTimeout after 15s",
        severity=SEVERITY_INFO,
        retryable=True,
        created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        resolved_at=None,
    )

    assert error.source == SOURCE_DENTALINK
    assert error.error_type == "dentalink_timeout"
    assert error.retryable is True


def test_error_records_with_different_severity_are_not_equal():
    created_at = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    base_kwargs = {
        "id": "err-2",
        "trace_id": None,
        "conversation_id": None,
        "agent_run_id": None,
        "source": SOURCE_DENTALINK,
        "error_type": "dentalink_auth_error",
        "error_code": None,
        "message": "Authentication failed",
        "technical_detail": None,
        "retryable": False,
        "created_at": created_at,
        "resolved_at": None,
    }
    first = ErrorRecord(**base_kwargs, severity=SEVERITY_INFO)
    second = ErrorRecord(**base_kwargs, severity=SEVERITY_CRITICAL)

    assert first != second
