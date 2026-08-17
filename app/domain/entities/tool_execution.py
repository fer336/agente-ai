from dataclasses import dataclass
from datetime import datetime

#: `tool_executions.status`.
COMPLETED = "completed"
FAILED = "failed"


@dataclass
class ToolExecution:
    """One record per call to an external tool/service (PRD.md §41).

    `request_summary`/`response_summary` are short, privacy-safe text
    summaries built from an explicit per-callsite whitelist of safe fields
    (ids, counts, enums) — PRD.md §41's last line: "Nunca se deberán
    guardar tokens, credenciales ni información sensible innecesaria". A
    `Patient`'s full name/phone/DNI, for example, must never end up here.
    """

    id: str
    agent_run_id: str
    node_execution_id: str | None
    tool_name: str
    provider: str
    operation: str
    request_summary: str
    response_summary: str | None
    status: str
    http_status: str | None
    duration_ms: int
    error_id: str | None
    created_at: datetime
