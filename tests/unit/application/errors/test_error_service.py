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
from tests.fixtures.gateways import (
    make_error_repository,
    make_incident_repository,
    make_linear_gateway,
    make_telegram_notifier,
)
from tests.fixtures.seed_objects import make_error_record


def _service(
    repository=None,
    threshold_count=5,
    window_seconds=120,
    incident_repository=None,
    telegram_notifier=None,
    linear_gateway=None,
    incident_threshold_count=10,
    incident_threshold_window_seconds=300,
    telegram_alert_cooldown_seconds=900,
) -> ErrorService:
    return ErrorService(
        repository or make_error_repository(),
        incident_repository if incident_repository is not None else make_incident_repository(),
        telegram_notifier if telegram_notifier is not None else make_telegram_notifier(),
        linear_gateway if linear_gateway is not None else make_linear_gateway(),
        alert_threshold_count=threshold_count,
        alert_window_seconds=window_seconds,
        incident_threshold_count=incident_threshold_count,
        incident_threshold_window_seconds=incident_threshold_window_seconds,
        telegram_alert_cooldown_seconds=telegram_alert_cooldown_seconds,
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


# --- Incident dedup + Telegram/Linear (PRD.md §47-51) --------------------


@pytest.mark.asyncio
async def test_report_creates_one_incident_and_updates_it_on_a_repeat_fingerprint():
    incident_repository = make_incident_repository()
    service = _service(incident_repository=incident_repository)

    await service.report(
        source=SOURCE_APPLICATION,
        error_type=GRAPH_STATE_ERROR,
        message="boom",
        conversation_id=ConversationId(value="conv-1"),
        operation="some_node",
    )
    await service.report(
        source=SOURCE_APPLICATION,
        error_type=GRAPH_STATE_ERROR,
        message="boom again",
        conversation_id=ConversationId(value="conv-2"),
        operation="some_node",
    )

    open_incidents = await incident_repository.list_open()
    assert len(open_incidents) == 1
    incident = open_incidents[0]
    assert incident.fingerprint == "application:graph_state_error:some_node"
    assert incident.occurrences == 2
    assert incident.affected_conversations == 2


@pytest.mark.asyncio
async def test_report_never_touches_incidents_telegram_or_linear_for_warning():
    incident_repository = make_incident_repository()
    telegram_notifier = make_telegram_notifier()
    linear_gateway = make_linear_gateway()
    service = _service(
        incident_repository=incident_repository,
        telegram_notifier=telegram_notifier,
        linear_gateway=linear_gateway,
    )

    await service.report(
        source=SOURCE_APPLICATION, error_type=APPOINTMENT_SLOT_TAKEN, message="slot taken"
    )

    assert await incident_repository.list_open() == []
    assert telegram_notifier.sent_messages == []
    assert linear_gateway.created_issues == []


@pytest.mark.asyncio
async def test_report_always_notifies_telegram_for_error_severity():
    telegram_notifier = make_telegram_notifier()
    service = _service(telegram_notifier=telegram_notifier)

    await service.report(source=SOURCE_APPLICATION, error_type=GRAPH_STATE_ERROR, message="boom")

    assert len(telegram_notifier.sent_messages) == 1


@pytest.mark.asyncio
async def test_report_only_syncs_linear_for_error_severity_past_the_incident_threshold():
    linear_gateway = make_linear_gateway()
    service = _service(linear_gateway=linear_gateway, incident_threshold_count=3)

    for i in range(2):
        await service.report(
            source=SOURCE_APPLICATION, error_type=GRAPH_STATE_ERROR, message=f"boom {i}"
        )
    assert linear_gateway.created_issues == []

    await service.report(source=SOURCE_APPLICATION, error_type=GRAPH_STATE_ERROR, message="boom 3")

    assert len(linear_gateway.created_issues) == 1


@pytest.mark.asyncio
async def test_report_always_notifies_telegram_and_syncs_linear_for_critical():
    telegram_notifier = make_telegram_notifier()
    linear_gateway = make_linear_gateway()
    service = _service(telegram_notifier=telegram_notifier, linear_gateway=linear_gateway)

    await service.report(
        source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message="crashed"
    )

    assert len(telegram_notifier.sent_messages) == 1
    assert len(linear_gateway.created_issues) == 1


@pytest.mark.asyncio
async def test_report_reuses_the_same_linear_issue_on_a_repeat_past_threshold():
    linear_gateway = make_linear_gateway()
    service = _service(linear_gateway=linear_gateway)

    for i in range(2):
        await service.report(
            source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message=f"crash {i}"
        )

    assert len(linear_gateway.created_issues) == 1
    assert len(linear_gateway.comments) == 1


@pytest.mark.asyncio
async def test_telegram_cooldown_suppresses_a_second_notification_within_the_window():
    telegram_notifier = make_telegram_notifier()
    service = _service(telegram_notifier=telegram_notifier, telegram_alert_cooldown_seconds=900)

    await service.report(
        source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message="crash 1"
    )
    await service.report(
        source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message="crash 2"
    )

    assert len(telegram_notifier.sent_messages) == 1


@pytest.mark.asyncio
async def test_telegram_notifies_again_after_the_cooldown_elapses():
    incident_repository = make_incident_repository()
    telegram_notifier = make_telegram_notifier()
    service = _service(
        incident_repository=incident_repository,
        telegram_notifier=telegram_notifier,
        telegram_alert_cooldown_seconds=900,
    )

    await service.report(
        source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message="crash 1"
    )
    assert len(telegram_notifier.sent_messages) == 1

    # Simulate the cooldown having elapsed by rewinding the incident's own
    # `last_notification_at` — avoids monkeypatching `datetime.now` just to
    # exercise this one comparison.
    incident = (await incident_repository.list_open())[0]
    incident.last_notification_at = incident.last_notification_at - timedelta(seconds=1000)
    await incident_repository.update(incident)

    await service.report(
        source=SOURCE_APPLICATION, error_type=UNEXPECTED_EXCEPTION, message="crash 2"
    )

    assert len(telegram_notifier.sent_messages) == 2
