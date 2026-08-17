import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.errors.error_types import (
    AGREEMENT_NOT_FOUND,
    APPOINTMENT_NOT_FOUND,
    APPOINTMENT_SLOT_TAKEN,
    DATABASE_ERROR,
    DENTALINK_AUTH_ERROR,
    DENTALINK_INVALID_RESPONSE,
    DENTALINK_TIMEOUT,
    GRAPH_STATE_ERROR,
    INVALID_LLM_OUTPUT,
    INVALID_TOOL_ARGUMENTS,
    OPENAI_TIMEOUT,
    PATIENT_NOT_FOUND,
    REDIS_ERROR,
    UNEXPECTED_EXCEPTION,
    UNKNOWN_INTENT,
    YCLOUD_AUTH_ERROR,
    YCLOUD_ERROR,
    YCLOUD_SEND_FAILURE,
    YCLOUD_WEBHOOK_FAILURE,
    is_retryable,
)
from app.domain.entities.error_record import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ErrorRecord,
)
from app.domain.repositories.error_repository import ErrorRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)

#: PRD.md §46 INFO — normal business events, never an alert.
_ALWAYS_INFO = frozenset({PATIENT_NOT_FOUND, APPOINTMENT_NOT_FOUND, AGREEMENT_NOT_FOUND})

#: PRD.md §46 WARNING — anomalous but not yet actionable, regardless of frequency.
_ALWAYS_WARNING = frozenset({APPOINTMENT_SLOT_TAKEN})

#: §46 only ever shows "unknown_intent repetido" at WARNING — unlike the
#: integration/agent errors below, it never escalates further just from
#: repeating; it is a conversation-quality signal, not a system-health one.
_WARNING_EVEN_WHEN_REPEATED = frozenset({UNKNOWN_INTENT})

#: PRD.md §46 ERROR — always, no isolated/repeated distinction given.
_ALWAYS_ERROR = frozenset({GRAPH_STATE_ERROR, INVALID_TOOL_ARGUMENTS, REDIS_ERROR})

#: PRD.md §46 CRITICAL — always requires immediate intervention.
_ALWAYS_CRITICAL = frozenset(
    {
        DENTALINK_AUTH_ERROR,
        YCLOUD_AUTH_ERROR,
        YCLOUD_WEBHOOK_FAILURE,
        DATABASE_ERROR,
        UNEXPECTED_EXCEPTION,
    }
)

#: PRD.md §46's "aislado" (WARNING) vs "repetido" (ERROR) pattern —
#: dentalink_timeout/openai_timeout are §46's own literal examples;
#: ycloud_error/dentalink_invalid_response/ycloud_send_failure/
#: invalid_llm_output are extrapolated consistently with that same pattern
#: (see this change's report).
_ESCALATES_ON_REPETITION = frozenset(
    {
        DENTALINK_TIMEOUT,
        DENTALINK_INVALID_RESPONSE,
        YCLOUD_ERROR,
        YCLOUD_SEND_FAILURE,
        OPENAI_TIMEOUT,
        INVALID_LLM_OUTPUT,
    }
)

_LOG_LEVEL_BY_SEVERITY = {
    SEVERITY_INFO: logging.INFO,
    SEVERITY_WARNING: logging.WARNING,
    SEVERITY_ERROR: logging.ERROR,
    SEVERITY_CRITICAL: logging.CRITICAL,
}


class ErrorService:
    """Concentrates error classification and (eventually) alerting behind
    one service (PRD.md §45, §52) — "la lógica del agente no deberá
    conocer directamente Telegram ni Linear".

    This change wires `report`/`classify` (PostgreSQL `errors` +
    `logging`, PRD.md §45's first two boxes) — `update_incident`/
    `notify_telegram`/`sync_linear` are a deliberately deferred follow-up
    (PRD.md §47-51: incident dedup + Telegram + Linear), see this change's
    report for why.
    """

    def __init__(
        self,
        error_repository: ErrorRepository,
        alert_threshold_count: int,
        alert_window_seconds: int,
    ) -> None:
        self._error_repository = error_repository
        self._alert_threshold_count = alert_threshold_count
        self._alert_window_seconds = alert_window_seconds

    async def report(
        self,
        *,
        source: str,
        error_type: str,
        message: str,
        trace_id: str | None = None,
        conversation_id: ConversationId | None = None,
        agent_run_id: str | None = None,
        error_code: str | None = None,
        technical_detail: str | None = None,
    ) -> ErrorRecord:
        severity = await self.classify(source=source, error_type=error_type)
        error = ErrorRecord(
            id=str(uuid4()),
            trace_id=trace_id,
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            source=source,
            error_type=error_type,
            error_code=error_code,
            message=message,
            technical_detail=technical_detail,
            severity=severity,
            retryable=is_retryable(error_type),
            created_at=datetime.now(UTC),
            resolved_at=None,
        )
        await self._error_repository.save(error)
        logger.log(
            _LOG_LEVEL_BY_SEVERITY[severity],
            "error_service.report source=%s error_type=%s severity=%s error_id=%s",
            source,
            error_type,
            severity,
            error.id,
            extra={
                "source": source,
                "error_type": error_type,
                "severity": severity,
                "error_id": error.id,
                "trace_id": trace_id,
                "agent_run_id": agent_run_id,
            },
        )
        return error

    async def classify(self, *, source: str, error_type: str) -> str:
        """Derives severity from `error_type` alone (PRD.md §46) — `source`
        is accepted (matching §52's conceptual signature, which pairs them)
        but unused by the rules themselves: every classified `error_type`
        in this catalog already implies exactly one source.
        """
        if error_type in _ALWAYS_INFO:
            return SEVERITY_INFO
        if error_type in _ALWAYS_CRITICAL:
            return SEVERITY_CRITICAL
        if error_type in _ALWAYS_ERROR:
            return SEVERITY_ERROR
        if error_type in _WARNING_EVEN_WHEN_REPEATED:
            return SEVERITY_WARNING
        if error_type in _ALWAYS_WARNING:
            return SEVERITY_WARNING
        if error_type in _ESCALATES_ON_REPETITION:
            since = datetime.now(UTC) - timedelta(seconds=self._alert_window_seconds)
            recent_count = await self._error_repository.count_recent(source, error_type, since)
            # +1 accounts for the occurrence being classified right now,
            # not yet persisted — PRD.md §50's own example ("5 timeouts en
            # 2 minutos") counts the 5th occurrence itself as the trigger.
            if recent_count + 1 >= self._alert_threshold_count:
                return SEVERITY_ERROR
            return SEVERITY_WARNING
        # An error_type this catalog doesn't recognize — default to
        # WARNING rather than silently under- or over-alerting.
        return SEVERITY_WARNING
