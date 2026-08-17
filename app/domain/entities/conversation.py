from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId


@dataclass
class Conversation:
    """Minimal conversation shell, sized to type gateway Protocol signatures.

    `mode` (PRD.md §23: `agent`/`human`/`closed`) governs whether LangGraph
    responds at all. `input_state` (PRD.md §6/§24.2: `FREE_INPUT`/
    `INTERACTIVE_SELECTION`/`SENSITIVE_CONFIRMATION`/`HUMAN`) is a distinct,
    separately-tracked concern — which KINDS of inbound message can
    advance the conversation right now. A conversation can be `mode="agent"`
    while `input_state="SENSITIVE_CONFIRMATION"` (bot is active, but only a
    button tied to the live `PendingAction` may confirm/reject — free text
    or audio never does, PRD.md §24.4).
    """

    id: ConversationId
    contact_id: str
    mode: str
    created_at: datetime
    input_state: str = "FREE_INPUT"
