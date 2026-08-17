from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId

#: PRD.md §39's documented `agent_runs.status` enum.
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
HANDOFF = "handoff"


@dataclass
class AgentRun:
    """One record per message processed by the LangGraph agent (PRD.md §39).

    Answers §38's own stated goal: "¿qué paciente estaba conversando? ¿qué
    mensaje inició la ejecución? ¿en qué nodo falló?" — `current_node` is
    updated as the graph progresses, `error_id` links to the `ErrorRecord`
    that ended the run when `status` is `failed`.
    """

    id: str
    conversation_id: ConversationId
    message_id: str
    trace_id: str
    prompt_version: str
    model: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    current_node: str | None
    error_id: str | None
