from app.infrastructure.chatwoot.schemas import (
    ChatwootConversationStatusChangedEventPayload,
    ChatwootConversationUpdatedEventPayload,
    ChatwootMessageCreatedEventPayload,
)
from app.infrastructure.chatwoot.webhook_parser import (
    extract_control_label_change,
    extract_resolved_conversation_id,
    extract_staff_reply,
    is_conversation_resolved_event,
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


def _transition_payload(
    previous: list[str], current: list[str]
) -> ChatwootConversationUpdatedEventPayload:
    return ChatwootConversationUpdatedEventPayload.model_validate(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {"label_list": {"previous_value": previous, "current_value": current}}
            ],
        }
    )


def test_adding_agente_while_administracion_is_on_hands_control_to_the_bot():
    payload = _transition_payload(["administracion"], ["administracion", "agente"])

    assert extract_control_label_change(payload) == ("99", "agent")


def test_adding_administracion_while_agente_is_on_hands_control_to_staff():
    payload = _transition_payload(["agente"], ["agente", "administracion"])

    assert extract_control_label_change(payload) == ("99", "human")


def test_cached_label_list_added_agente_wins_over_the_previous_administracion():
    payload = ChatwootConversationUpdatedEventPayload.model_validate(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {
                    "cached_label_list": {
                        "previous_value": "administracion",
                        "current_value": "administracion,agente",
                    }
                }
            ],
        }
    )

    assert extract_control_label_change(payload) == ("99", "agent")


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


def _cached_labels_payload(current: str) -> ChatwootConversationUpdatedEventPayload:
    # Chatwoot can report label changes through the `cached_label_list` column:
    # a comma-separated string, not a list.
    return ChatwootConversationUpdatedEventPayload.model_validate(
        {
            "event": "conversation_updated",
            "id": 99,
            "changed_attributes": [
                {"updated_at": {"previous_value": "a", "current_value": "b"}},
                {"cached_label_list": {"previous_value": "agente", "current_value": current}},
            ],
        }
    )


def test_cached_label_list_with_administracion_pauses_the_bot():
    # Live case: conversation_updated arrived after setting "administracion" and the
    # bot kept answering, because only `label_list` was recognised.
    assert extract_control_label_change(_cached_labels_payload("vip,administracion")) == (
        "99",
        "human",
    )


def test_cached_label_list_with_agente_reactivates_the_bot():
    assert extract_control_label_change(_cached_labels_payload("agente")) == ("99", "agent")


def test_cached_label_list_tolerates_spaces_after_commas():
    assert extract_control_label_change(_cached_labels_payload("vip, administracion")) == (
        "99",
        "human",
    )


def test_is_conversation_resolved_event():
    assert is_conversation_resolved_event("conversation_resolved") is True
    assert is_conversation_resolved_event("conversation_status_changed") is False


def test_extract_resolved_conversation_id_treats_the_resolved_event_as_resolved_without_status():
    payload = ChatwootConversationStatusChangedEventPayload.model_validate(
        {"event": "conversation_resolved", "id": 43}
    )

    assert extract_resolved_conversation_id(payload) == "43"
