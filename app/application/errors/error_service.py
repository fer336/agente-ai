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
from app.domain.entities.incident import INCIDENT_OPEN, Incident
from app.domain.repositories.alert_notifier import AlertNotifier
from app.domain.repositories.error_repository import ErrorRepository
from app.domain.repositories.incident_gateway import IncidentGateway
from app.domain.repositories.incident_repository import IncidentRepository
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
    """Concentrates error classification and alerting behind one service
    (PRD.md §45, §52) — "la lógica del agente no deberá conocer
    directamente Telegram ni Linear".

    `report`/`classify` persist to PostgreSQL `errors` + `logging` (PRD.md
    §45's first two boxes) for every severity. For ERROR/CRITICAL only,
    `report` also calls `update_incident` (fingerprint dedup, PRD.md §49),
    `notify_telegram` (always, subject to a cooldown), and `sync_linear`
    (CRITICAL always; ERROR only once the fingerprint's occurrences within
    `incident_threshold_window_seconds` reach `incident_threshold_count`,
    PRD.md §46/§50). WARNING/INFO never touch incidents/Telegram/Linear.

    A Telegram/Linear delivery failure is caught and logged inside
    `notify_telegram`/`sync_linear` themselves — it must never propagate
    back into `report()`'s caller (PRD.md §47: Telegram/Linear are alert
    channels, not the source of truth the rest of the system depends on).
    """

    def __init__(
        self,
        error_repository: ErrorRepository,
        incident_repository: IncidentRepository,
        telegram_notifier: AlertNotifier,
        linear_gateway: IncidentGateway,
        alert_threshold_count: int,
        alert_window_seconds: int,
        incident_threshold_count: int,
        incident_threshold_window_seconds: int,
        telegram_alert_cooldown_seconds: int,
    ) -> None:
        self._error_repository = error_repository
        self._incident_repository = incident_repository
        self._telegram_notifier = telegram_notifier
        self._linear_gateway = linear_gateway
        self._alert_threshold_count = alert_threshold_count
        self._alert_window_seconds = alert_window_seconds
        self._incident_threshold_count = incident_threshold_count
        self._incident_threshold_window_seconds = incident_threshold_window_seconds
        self._telegram_alert_cooldown_seconds = telegram_alert_cooldown_seconds

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
        operation: str | None = None,
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

        if severity in (SEVERITY_ERROR, SEVERITY_CRITICAL):
            incident = await self.update_incident(
                source=source,
                error_type=error_type,
                operation=operation,
                severity=severity,
                conversation_id=conversation_id,
                now=error.created_at,
            )
            await self.notify_telegram(incident, error)
            if await self._should_sync_linear(incident, source, error_type):
                await self.sync_linear(incident, error)

        return error

    @staticmethod
    def build_fingerprint(source: str, error_type: str, operation: str | None) -> str:
        """PRD.md §49: `provider:error_type:operation`, falling back to
        `provider:error_type` when no `operation` is available (no current
        `report()` caller hits the fallback, but it keeps `operation`
        optional for forward compatibility).
        """
        if operation is not None:
            return f"{source}:{error_type}:{operation}"
        return f"{source}:{error_type}"

    async def _should_sync_linear(self, incident: Incident, source: str, error_type: str) -> bool:
        if incident.severity == SEVERITY_CRITICAL:
            return True
        since = incident.last_seen - timedelta(seconds=self._incident_threshold_window_seconds)
        # Unlike `classify`'s own windowed count (run BEFORE its occurrence
        # is persisted, hence that check's own `+1`), this runs AFTER
        # `report()` already saved the current `ErrorRecord` — `count_recent`
        # already includes it, so no `+1` here.
        recent_count = await self._error_repository.count_recent(source, error_type, since)
        return recent_count >= self._incident_threshold_count

    async def update_incident(
        self,
        *,
        source: str,
        error_type: str,
        operation: str | None,
        severity: str,
        conversation_id: ConversationId | None,
        now: datetime,
    ) -> Incident:
        """Upserts the open incident for this fingerprint (PRD.md §49): a
        brand-new fingerprint creates one row; a repeat updates
        `occurrences`/`last_seen`/`affected_conversations` in place rather
        than creating a duplicate.

        `affected_conversations` is a simple per-occurrence counter (kept
        deliberately simple per `Incident`'s own docstring), not a true
        distinct-conversation count — a genuine dedup would require
        persisting the full set of conversation ids per incident, which
        this MVP-level table does not do.
        """
        fingerprint = self.build_fingerprint(source, error_type, operation)
        existing = await self._incident_repository.get_by_fingerprint(fingerprint)
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen = now
            if conversation_id is not None:
                existing.affected_conversations += 1
            if existing.severity != SEVERITY_CRITICAL:
                existing.severity = severity
            await self._incident_repository.update(existing)
            return existing

        incident = Incident(
            id=str(uuid4()),
            fingerprint=fingerprint,
            source=source,
            error_type=error_type,
            operation=operation,
            severity=severity,
            occurrences=1,
            affected_conversations=1 if conversation_id is not None else 0,
            first_seen=now,
            last_seen=now,
            status=INCIDENT_OPEN,
            linear_issue_id=None,
            last_notification_at=None,
            resolved_at=None,
        )
        await self._incident_repository.save(incident)
        return incident

    async def notify_telegram(self, incident: Incident, error: ErrorRecord) -> None:
        """Sends (or suppresses, per `telegram_alert_cooldown_seconds`) a
        Telegram alert for this incident (PRD.md §47/§50).
        """
        now = error.created_at
        if incident.last_notification_at is not None:
            elapsed = (now - incident.last_notification_at).total_seconds()
            if elapsed < self._telegram_alert_cooldown_seconds:
                return

        text = (
            f"🚨 {incident.severity} — {incident.source}\n\n"
            f"Error: {incident.error_type}\n"
            f"Nodo/Operación: {incident.operation or 'n/d'}\n\n"
            f"Ocurrencias: {incident.occurrences}\n"
            f"Conversaciones afectadas: {incident.affected_conversations}\n"
            f"Primera detección: {incident.first_seen.isoformat()}\n\n"
            f"Ver detalle:\n/admin/errors/{error.id}"
        )
        try:
            await self._telegram_notifier.notify(text)
        except Exception:  # noqa: BLE001 - a Telegram outage must never break error reporting
            logger.warning(
                "error_service.notify_telegram_failed incident_id=%s", incident.id, exc_info=True
            )
            return

        incident.last_notification_at = now
        await self._incident_repository.update(incident)

    async def sync_linear(self, incident: Incident, error: ErrorRecord) -> None:
        """Creates the incident's Linear issue on first sync, or comments
        on the existing one for a repeat occurrence (PRD.md §48/§49: "NO
        crear otro issue").
        """
        try:
            if incident.linear_issue_id is None:
                issue_id = await self._linear_gateway.create_issue(
                    title=f"[{incident.severity}][{incident.source.upper()}] {incident.error_type}",
                    description=(
                        f"Fingerprint: {incident.fingerprint}\n"
                        f"Occurrences: {incident.occurrences}\n"
                        f"Affected conversations: {incident.affected_conversations}\n"
                        f"First seen: {incident.first_seen.isoformat()}\n"
                        f"Last seen: {incident.last_seen.isoformat()}\n"
                        f"Admin: /admin/errors/{error.id}"
                    ),
                    priority="urgent" if incident.severity == SEVERITY_CRITICAL else "high",
                )
                incident.linear_issue_id = issue_id
            else:
                await self._linear_gateway.add_comment(
                    incident.linear_issue_id,
                    f"Occurrences: {incident.occurrences}\n"
                    f"Last seen: {incident.last_seen.isoformat()}",
                )
        except Exception:  # noqa: BLE001 - a Linear outage must never break error reporting
            logger.warning(
                "error_service.sync_linear_failed incident_id=%s", incident.id, exc_info=True
            )
            return

        await self._incident_repository.update(incident)

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
