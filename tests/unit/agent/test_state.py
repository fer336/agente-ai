from app.agent.state import AgentState


def test_agent_state_accepts_all_fields_from_architecture_doc_section_9():
    state: AgentState = {
        "conversation_id": "conv-1",
        "message_ids": ["msg-1", "msg-2"],
        "user_message": "Quiero un turno",
        "intent": "schedule_appointment",
        "collected_data": {"specialty_id": "cleaning"},
        "missing_fields": ["date"],
        "pending_action_id": None,
        "response_text": None,
        "requires_handoff": False,
    }

    assert state["conversation_id"] == "conv-1"
    assert state["message_ids"] == ["msg-1", "msg-2"]
    assert state["requires_handoff"] is False


def test_agent_state_field_set_matches_architecture_doc_section_9_verbatim():
    assert set(AgentState.__annotations__) == {
        "conversation_id",
        "message_ids",
        "user_message",
        "intent",
        "collected_data",
        "missing_fields",
        "pending_action_id",
        "response_text",
        "requires_handoff",
    }
