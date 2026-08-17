from app.agent.state import AgentState


def test_agent_state_accepts_all_fields_from_prd_section_31():
    state: AgentState = {
        "conversation_id": "conv-1",
        "message_ids": ["msg-1", "msg-2"],
        "user_message": "Quiero un turno",
        "button_payload": None,
        "intent": "appointment",
        "appointment_action": "create",
        "collected_data": {"specialty_id": "cleaning"},
        "missing_fields": ["date"],
        "pending_action_id": None,
        "response_text": None,
        "response_buttons": None,
        "requires_handoff": False,
        "error": None,
    }

    assert state["conversation_id"] == "conv-1"
    assert state["message_ids"] == ["msg-1", "msg-2"]
    assert state["requires_handoff"] is False


def test_agent_state_field_set_matches_prd_section_31_plus_repo_specific_fields():
    assert set(AgentState.__annotations__) == {
        "conversation_id",
        "message_ids",
        "user_message",
        "button_payload",
        "intent",
        "appointment_action",
        "collected_data",
        "missing_fields",
        "pending_action_id",
        "response_text",
        "response_buttons",
        "requires_handoff",
        "error",
    }
