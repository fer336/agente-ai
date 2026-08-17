from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId

#: `errors.source` — PRD.md §42's documented enum.
SOURCE_DENTALINK = "dentalink"
SOURCE_YCLOUD = "ycloud"
SOURCE_OPENAI = "openai"
SOURCE_POSTGRESQL = "postgresql"
SOURCE_REDIS = "redis"
SOURCE_LANGGRAPH = "langgraph"
SOURCE_APPLICATION = "application"

#: `errors.severity` — PRD.md §46's four levels.
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"


@dataclass
class ErrorRecord:
    """One record per error encountered by the agent or its integrations
    (PRD.md §42-43).

    `error_type` is one of PRD.md §43.1-43.4's classified tokens (e.g.
    `patient_not_found`, `dentalink_timeout`, `database_error`,
    `invalid_llm_output`) — see `app.application.errors.error_types` for
    the full catalog and `ErrorService.classify` for how `severity` is
    derived from it (PRD.md §46).
    """

    id: str
    trace_id: str | None
    conversation_id: ConversationId | None
    agent_run_id: str | None
    source: str
    error_type: str
    error_code: str | None
    message: str
    technical_detail: str | None
    severity: str
    retryable: bool
    created_at: datetime
    resolved_at: datetime | None
