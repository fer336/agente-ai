"""Shared `AgentState` builder for LangGraph node tests.

Plain factory function (not a `@pytest.fixture`) — `AgentState` is a
TypedDict with no setup/teardown lifecycle, matching this repo's other
`tests/fixtures/*.py` factory-function convention.
"""

from app.agent.state import AgentState


def make_agent_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "conversation_id": "conv-1",
        "message_ids": ["msg-1"],
        "user_message": "Necesito un turno",
        "button_payload": None,
        "recent_messages": [],
        "contact_memory_summary": None,
        "intent": None,
        "appointment_action": None,
        "collected_data": {},
        "missing_fields": [],
        "pending_action_id": None,
        "response_text": None,
        "response_buttons": None,
        "requires_handoff": False,
        "error": None,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base
