from app.infrastructure.chatwoot.schemas import (
    ChatwootConversationStatusChangedEventPayload,
    ChatwootConversationUpdatedEventPayload,
    ChatwootMessageCreatedEventPayload,
)
from app.infrastructure.chatwoot.webhook_parser import (
    extract_control_label_change,
    extract_resolved_conversation_id,
    extract_staff_reply,
    is_conversation_status_changed_event,
    is_conversation_updated_event,
    is_message_created_event,
)


def _message_payload(**overrides: object) -> ChatwootMessageCreatedEventPayload:
    base: dict[str, object] = {
        "event": "message_created",
        "message_type": "outgoing",
        "content": "Hola, te confirmo el turno",
        "conversation": {"id": 99},
        "sender": {"id": 5, "type": "user"},
    }
    base.update(overrides)
    return ChatwootMessageCreatedEventPayload.model_validate(base)


def test_is_message_created_event():
    assert is_message_created_event("message_created") is True
    assert is_message_created_event("conversation_status_changed") is False


def test_is_conversation_status_changed_event():
    assert is_conversation_status_changed_event("conversation_status_changed") is True
    assert is_conversation_status_changed_event("message_created") is False


def test_is_conversation_updated_event():
    assert is_conversation_updated_event("conversation_updated") is True
    assert is_conversation_updated_event("message_created") is False


def test_extract_staff_reply_returns_conversation_id_and_content_for_a_human_agent():
    result = extract_staff_reply(_message_payload())

    assert result == ("99", "Hola, te confirmo el turno")


def test_extract_staff_reply_ignores_the_bots_own_mirrored_message():
    # sender.type="agent_bot" -- our own bot's mirrored WhatsApp reply,
    # not a human typing in Chatwoot. Must not be forwarded back, or every
    # bot reply would loop forever.
    result = extract_staff_reply(_message_payload(sender={"id": 1, "type": "agent_bot"}))

    assert result is None


def test_extract_staff_reply_ignores_a_patient_message():
    result = extract_staff_reply(
        _message_payload(message_type="incoming", sender={"id": 2, "type": "contact"})
    )

    assert result is None


def test_extract_staff_reply_ignores_empty_content():
    result = extract_staff_reply(_message_payload(content=""))

    assert result is None


def test_extract_staff_reply_ignores_a_missing_conversation_id():
    result = extract_staff_reply(_message_payload(conversation={"id": 0}))

    assert result is None


def test_extract_resolved_conversation_id_returns_the_id_for_a_resolved_status():
    payload = ChatwootConversationStatusChangedEventPayload.model_validate(
        {"event": "conversation_status_changed", "id": 99, "status": "resolved"}
    )

    assert extract_resolved_conversation_id(payload) == "99"


def test_extract_resolved_conversation_id_ignores_other_statuses():
    payload = ChatwootConversationStatusChangedEventPayload.model_validate(
        {"event": "conversation_status_changed", "id": 99, "status": "open"}
    )

    assert extract_resolved_conversation_id(payload) is None


def _updated_payload(labels: list[str]) -> ChatwootConversationUpdatedEventPayload:
    return ChatwootConversationUpdatedEventPayload.model_validate(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {
                    "label_list": {
                        "previous_value": [],
                        "current_value": labels,
                    }
                }
            ],
        }
    )


def test_extract_control_label_change_pauses_for_administracion():
    assert extract_control_label_change(_updated_payload(["vip", "administracion"])) == (
        "99",
        "human",
    )


def test_extract_control_label_change_reactivates_for_agente():
    assert extract_control_label_change(_updated_payload(["vip", "agente"])) == (
        "99",
        "agent",
    )


def test_extract_control_label_change_gives_administracion_precedence():
    assert extract_control_label_change(_updated_payload(["agente", "administracion"])) == (
        "99",
        "human",
    )


def test_extract_control_label_change_ignores_unrelated_labels():
    assert extract_control_label_change(_updated_payload(["vip"])) is None


def test_extract_control_label_change_ignores_updates_without_label_changes():
    payload = ChatwootConversationUpdatedEventPayload.model_validate(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [{"status": {"current_value": "open"}}],
        }
    )

    assert extract_control_label_change(payload) is None
