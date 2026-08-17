from typing import TypedDict

from app.domain.value_objects.interactive_button import InteractiveButton


class AgentState(TypedDict):
    """LangGraph conversational state (PRD.md §31).

    Holds only conversational information. Critical actions (e.g. a pending
    cancellation) MUST NOT live solely inside this graph state — they are
    persisted separately in PostgreSQL (see PRD.md §16).
    """

    conversation_id: str
    message_ids: list[str]
    user_message: str
    #: Machine-readable id of a tapped interactive button (PRD.md §6),
    #: `None` for free text/audio. Set once per turn from `AgentInvoker.handle`'s
    #: own `button_payload` argument — never mutated by a node.
    button_payload: str | None
    intent: str | None
    appointment_action: str | None
    collected_data: dict[str, object]
    missing_fields: list[str]
    pending_action_id: str | None
    response_text: str | None
    #: Interactive buttons to send alongside `response_text` (PRD.md §6's
    #: `INTERACTIVE_SELECTION`/`SENSITIVE_CONFIRMATION` states). `None` (or
    #: empty) sends a plain text reply instead. Reset fresh every turn by
    #: `AgentInvoker.handle` — never carried over via the checkpointer.
    response_buttons: list[InteractiveButton] | None
    requires_handoff: bool
    #: Set by a node's error-handling wrapper (not part of PRD.md §31's
    #: literal field list) when the node's business logic raised — routes
    #: to the `handle_error` node. Cleared on the next successful turn.
    error: str | None
