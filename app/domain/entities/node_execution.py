from dataclasses import dataclass
from datetime import datetime

#: `node_executions.status` — PRD.md §40's example shows only a binary
#: ✓/✗ result per node (a node call is synchronous and short-lived, unlike
#: an `AgentRun`, so there is no useful `running` state to persist — see
#: `with_error_handling`'s own docstring for why this is written once, after
#: the node call finishes, rather than twice).
COMPLETED = "completed"
FAILED = "failed"


@dataclass
class NodeExecution:
    """One record per LangGraph node executed within an `AgentRun` (PRD.md §40).

    `input_summary`/`output_summary` are short, privacy-safe text summaries
    — never the raw `AgentState`, which can carry a patient's free-text
    identification message (name + DNI, PRD.md §32) or other PII.
    """

    id: str
    agent_run_id: str
    node_name: str
    started_at: datetime
    finished_at: datetime
    status: str
    input_summary: str
    output_summary: str
    duration_ms: int
    error_id: str | None
