from dataclasses import dataclass
from datetime import datetime

#: `incidents.status` — PRD.md §51.
INCIDENT_OPEN = "open"
INCIDENT_RECOVERED = "recovered"


@dataclass
class Incident:
    """One deduplicated incident per `fingerprint` (PRD.md §49).

    `fingerprint` groups repeated `ErrorRecord`s (`source:error_type:operation`,
    or `source:error_type` when no `operation` is available — see
    `ErrorService.build_fingerprint`) so a burst of the same failure creates
    ONE row here, updated in place (`occurrences`/`last_seen`/
    `affected_conversations`), rather than a fresh Linear issue per
    occurrence.
    """

    id: str
    fingerprint: str
    source: str
    error_type: str
    operation: str | None
    severity: str
    occurrences: int
    affected_conversations: int
    first_seen: datetime
    last_seen: datetime
    status: str
    linear_issue_id: str | None
    last_notification_at: datetime | None
    resolved_at: datetime | None
