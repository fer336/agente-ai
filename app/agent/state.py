from typing import TypedDict

from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage
from app.domain.value_objects.location_request import LocationRequest


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
    #: Conversational-memory module's bounded context (no PRD.md section
    #: number — this session's own brief), populated once per turn by
    #: `LangGraphAgentInvoker.handle()` before `graph.ainvoke()`. `[]`/`None`
    #: when the contact/conversation lookup fails — never blocks a turn.
    recent_messages: list[dict[str, str]]
    contact_memory_summary: str | None
    #: The name to greet a RETURNING contact by (this session's own
    #: brief), resolved once per turn by `LangGraphAgentInvoker.handle()`
    #: from `Contact.patient_id` — `None` for a first-time or unlinked
    #: contact. Text only: no node may use this to skip identification
    #: before a sensitive operation (`PatientGateway.get_patient_by_id`'s
    #: own docstring) — the phone number alone is never sufficient proof.
    known_patient_name: str | None
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
    #: A WhatsApp Flow to send instead of plain text/buttons (this
    #: session's own brief — no PRD.md section). Takes priority over
    #: `response_buttons` when both are somehow set; a node should only
    #: ever set one. `None` sends a normal text/button reply.
    response_flow: FlowRequest | None
    #: A native WhatsApp location card to send instead of plain text/a
    #: Flow — WhatsApp's location message type carries no text body of
    #: its own, so `response_text` is ignored on this path. `None` sends
    #: a normal reply.
    response_location: LocationRequest | None
    #: An interactive list to send instead of plain text/buttons — for a
    #: menu with more than 3 options but still within WhatsApp's 10-row
    #: cap. `None` sends a normal reply.
    response_list: ListMessage | None
    requires_handoff: bool
    #: Set by a node's error-handling wrapper (not part of PRD.md §31's
    #: literal field list) when the node's business logic raised — routes
    #: to the `handle_error` node. Cleared on the next successful turn.
    error: str | None
