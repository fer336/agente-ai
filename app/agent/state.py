from typing import TypedDict


class AgentState(TypedDict):
    """LangGraph conversational state (architecture doc §9, verbatim).

    Holds only conversational information. Critical actions (e.g. a pending
    cancellation) MUST NOT live solely inside this graph state — they are
    persisted separately in PostgreSQL (see doc §10).
    """

    conversation_id: str
    message_ids: list[str]
    user_message: str
    intent: str | None
    collected_data: dict[str, object]
    missing_fields: list[str]
    pending_action_id: str | None
    response_text: str | None
    requires_handoff: bool
