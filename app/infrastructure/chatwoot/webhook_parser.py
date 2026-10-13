from app.infrastructure.chatwoot.schemas import (
    ChatwootConversationChangedAttribute,
    ChatwootConversationStatusChangedEventPayload,
    ChatwootConversationUpdatedEventPayload,
    ChatwootMessageCreatedEventPayload,
)

_MESSAGE_CREATED_EVENT = "message_created"
_CONVERSATION_STATUS_CHANGED_EVENT = "conversation_status_changed"
_CONVERSATION_UPDATED_EVENT = "conversation_updated"
_CONVERSATION_RESOLVED_EVENT = "conversation_resolved"
_OUTGOING_MESSAGE_TYPE = "outgoing"
#: Confirmed live (see `app.infrastructure.chatwoot.schemas`'s own
#: docstring): a human agent's own personal token is what attributes a
#: message as `sender.type == "user"` — our own bot's mirrored messages
#: come back as `"agent_bot"` instead (different token), and a patient's
#: own messages as `"contact"` (always `message_type == "incoming"`, never
#: reaches this branch). This is what tells a staff-typed Chatwoot reply
#: apart from our own bot's mirrored echo of its own WhatsApp reply,
#: preventing an infinite forward loop.
_HUMAN_SENDER_TYPE = "user"
_RESOLVED_STATUS = "resolved"
_ADMINISTRACION_LABEL = "administracion"
_AGENT_LABEL = "agente"


def is_message_created_event(event: str) -> bool:
    return event == _MESSAGE_CREATED_EVENT


def is_conversation_status_changed_event(event: str) -> bool:
    return event == _CONVERSATION_STATUS_CHANGED_EVENT


def is_conversation_resolved_event(event: str) -> bool:
    return event == _CONVERSATION_RESOLVED_EVENT


def is_conversation_updated_event(event: str) -> bool:
    return event == _CONVERSATION_UPDATED_EVENT


def extract_staff_reply(payload: ChatwootMessageCreatedEventPayload) -> tuple[str, str] | None:
    """Returns `(chatwoot_conversation_id, content)` for a message a human
    STAFF member typed in Chatwoot, else `None` — filters out the bot's own
    mirrored outgoing messages (`sender.type == "agent_bot"`) and patient
    messages (`sender.type == "contact"`), so this event is never echoed
    back to WhatsApp in a loop.
    """
    if payload.message_type != _OUTGOING_MESSAGE_TYPE:
        return None
    if payload.sender.type != _HUMAN_SENDER_TYPE:
        return None
    if not payload.content or not payload.content.strip():
        return None
    if not payload.conversation.id:
        return None
    return str(payload.conversation.id), payload.content


def _current_labels(changed_attribute: ChatwootConversationChangedAttribute) -> set[str] | None:
    """The labels after the change, from `label_list` (a list) or `cached_label_list`
    (a comma-separated string); `None` when this entry is not a label change."""
    if changed_attribute.label_list is not None:
        return {label.strip() for label in changed_attribute.label_list.current_value}
    if changed_attribute.cached_label_list is not None:
        raw = changed_attribute.cached_label_list.current_value or ""
        return {label.strip() for label in raw.split(",") if label.strip()}
    return None


def extract_control_label_change(
    payload: ChatwootConversationUpdatedEventPayload,
) -> tuple[str, str] | None:
    """Returns `(conversation_id, mode)` for a control-label update.

    `administracion` wins if both control labels are present, failing safe to
    human control. Duplicate webhook deliveries are harmless because setting
    either local mode is idempotent.
    """
    if not payload.id:
        return None
    for changed_attribute in payload.changed_attributes:
        labels = _current_labels(changed_attribute)
        if labels is None:
            continue
        if _ADMINISTRACION_LABEL in labels:
            return str(payload.id), "human"
        if _AGENT_LABEL in labels:
            return str(payload.id), "agent"
        return None
    return None


def extract_resolved_conversation_id(
    payload: ChatwootConversationStatusChangedEventPayload,
) -> str | None:
    """Returns the Chatwoot conversation id for a `status="resolved"`
    event, else `None` (`open`/`pending`/`snoozed` need no reaction here).
    A `conversation_resolved` event (Agent Bot delivery) is resolved by its
    name alone, even when `status` is missing."""
    if payload.status != _RESOLVED_STATUS and payload.event != _CONVERSATION_RESOLVED_EVENT:
        return None
    if not payload.id:
        return None
    return str(payload.id)
