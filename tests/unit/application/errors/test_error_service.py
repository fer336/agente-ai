from datetime import UTC, datetime, timedelta

import pytest

from app.application.errors.error_service import ErrorService
from app.application.errors.error_types import (
    AGREEMENT_NOT_FOUND,
    APPOINTMENT_NOT_FOUND,
    APPOINTMENT_SLOT_TAKEN,
    DATABASE_ERROR,
    DENTALINK_AUTH_ERROR,
    DENTALINK_TIMEOUT,
    GRAPH_STATE_ERROR,
    INVALID_TOOL_ARGUMENTS,
    PATIENT_NOT_FOUND,
    REDIS_ERROR,
    UNEXPECTED_EXCEPTION,
    UNKNOWN_INTENT,
    YCLOUD_AUTH_ERROR,
    YCLOUD_WEBHOOK_FAILURE,
)
from app.domain.entities.error_record import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SOURCE_APPLICATION,
    SOURCE_DENTALINK,
)
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import make_error_repository
from tests.fixtures.seed_objects import make_error_record


def _service(repository=None, threshold_count=5, window_seconds=120) -> ErrorService:
    return ErrorService(
        repository or make_error_repository(),
        alert_threshold_count=threshold_count,
        alert_window_seconds=window_seconds,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type", [PATIENT_NOT_FOUND, APPOINTMENT_NOT_FOUND, AGREEMENT_NOT_FOUND]
)
async def test_classify_business_not_found_errors_as_info(error_type):
    severity = await _service().classify(source=SOURCE_APPLICATION, error_type=error_type)

    assert severity == SEVERITY_INFO


@pytest.mark.asyncio
async def test_classify_appointment_slot_taken_as_warning():
    severity = await _service().classify(
        source=SOURCE_APPLICATION, error_type=APPOINTMENT_SLOT_TAKEN
    )

    assert severity == SEVERITY_WARNING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [
        DENTALINK_AUTH_ERROR,
        YCLOUD_AUTH_ERROR,
        YCLOUD_WEBHOOK_FAILURE,
        DATABASE_ERROR,
        UNEXPECTED_EXCEPTION,
    ],
)
async def test_classify_always_critical_errors(error_type):
    severity = await _service().classify(source=SOURCE_APPLICATION, error_type=error_type)

    assert severity == SEVERITY_CRITICAL


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [GRAPH_STATE_ERROR, INVALID_TOOL_ARGUMENTS, REDIS_ERROR])
async def test_classify_always_error_severity(error_type):
    severity = await _service().classify(source=SOURCE_APPLICATION, error_type=error_type)

    assert severity == SEVERITY_ERROR


@pytest.mark.asyncio
async def test_classify_dentalink_timeout_as_warning_when_isolated():
    severity = await _service().classify(source=SOURCE_DENTALINK, error_type=DENTALINK_TIMEOUT)

    assert severity == SEVERITY_WARNING


@pytest.mark.asyncio
async def test_classify_dentalink_timeout_as_error_when_repeated_past_threshold():
    repository = make_error_repository()
    now = datetime.now(UTC)
    for i in range(4):
        await repository.save(
            make_error_record(
                id_=f"err-{i}",
                source=SOURCE_DENTALINK,
                error_type=DENTALINK_TIMEOUT,
                created_at=now - timedelta(seconds=10),
            )
        )

    severity = await _service(repository, threshold_count=5).classify(
        source=SOURCE_DENTALINK, error_type=DENTALINK_TIMEOUT
    )

    assert severity == SEVERITY_ERROR


@pytest.mark.asyncio
async def test_classify_dentalink_timeout_ignores_occurrences_outside_the_window():
    repository = make_error_repository()
    now = datetime.now(UTC)
    for i in range(4):
        await repository.save(
            make_error_record(
                id_=f"err-{i}",
                source=SOURCE_DENTALINK,
                error_type=DENTALINK_TIMEOUT,
                created_at=now - timedelta(seconds=999),
            )
        )

    severity = await _service(repository, threshold_count=5, window_seconds=120).classify(
        source=SOURCE_DENTALINK, error_type=DENTALINK_TIMEOUT
    )

    assert severity == SEVERITY_WARNING


@pytest.mark.asyncio
async def test_classify_unknown_intent_stays_warning_even_when_repeated():
    repository = make_error_repository()
    now = datetime.now(UTC)
    for i in range(10):
        await repository.save(
            make_error_record(
                id_=f"err-{i}",
                source=SOURCE_APPLICATION,
                error_type=UNKNOWN_INTENT,
                created_at=now,
            )
        )

    severity = await _service(repository, threshold_count=5).classify(
        source=SOURCE_APPLICATION, error_type=UNKNOWN_INTENT
    )

    assert severity == SEVERITY_WARNING


@pytest.mark.asyncio
async def test_classify_defaults_unrecognized_error_types_to_warning():
    severity = await _service().classify(source=SOURCE_APPLICATION, error_type="something_new")

    assert severity == SEVERITY_WARNING


@pytest.mark.asyncio
async def test_report_persists_and_returns_a_classified_error_record():
    repository = make_error_repository()
    service = _service(repository)

    error = await service.report(
        source=SOURCE_DENTALINK,
        error_type=DENTALINK_TIMEOUT,
        message="Dentalink did not respond in time",
        trace_id="trace-1",
        conversation_id=ConversationId(value="conv-1"),
        agent_run_id="run-1",
        technical_detail="httpx.ReadTimeout after 15s",
    )

    assert error.severity == SEVERITY_WARNING
    assert error.retryable is True
    assert error.source == SOURCE_DENTALINK
    assert error.error_type == DENTALINK_TIMEOUT
    fetched = await repository.get_by_id(error.id)
    assert fetched is not None
    assert fetched.message == "Dentalink did not respond in time"


@pytest.mark.asyncio
async def test_report_marks_business_errors_as_not_retryable():
    service = _service()

    error = await service.report(
        source=SOURCE_APPLICATION,
        error_type=PATIENT_NOT_FOUND,
        message="No patient matched",
    )

    assert error.retryable is False
