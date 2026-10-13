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


def _split_labels(raw: str | None) -> set[str]:
    return {label.strip() for label in (raw or "").split(",") if label.strip()}


def _label_sets(
    changed_attribute: ChatwootConversationChangedAttribute,
) -> tuple[set[str], set[str]] | None:
    """`(previous, current)` labels from `label_list` (a list) or `cached_label_list`
    (a comma-separated string); `None` when this entry is not a label change."""
    if changed_attribute.label_list is not None:
        change = changed_attribute.label_list
        return (
            {label.strip() for label in change.previous_value},
            {label.strip() for label in change.current_value},
        )
    if changed_attribute.cached_label_list is not None:
        cached = changed_attribute.cached_label_list
        return _split_labels(cached.previous_value), _split_labels(cached.current_value)
    return None


def extract_control_label_change(
    payload: ChatwootConversationUpdatedEventPayload,
) -> tuple[str, str] | None:
    """Returns `(conversation_id, mode)` for a control-label update.

    When both control labels are present, the one staff just ADDED wins, so
    adding `agente` while `administracion` is still on hands control back to the
    bot in one click. If the added one cannot be told apart (both new, or no
    previous value), `administracion` wins, failing safe to human control.
    Duplicate webhook deliveries are harmless because setting either local mode
    is idempotent.
    """
    if not payload.id:
        return None
    for changed_attribute in payload.changed_attributes:
        label_sets = _label_sets(changed_attribute)
        if label_sets is None:
            continue
        previous, current = label_sets
        has_administracion = _ADMINISTRACION_LABEL in current
        has_agent = _AGENT_LABEL in current
        if has_administracion and has_agent:
            added = current - previous
            if _AGENT_LABEL in added and _ADMINISTRACION_LABEL not in added:
                return str(payload.id), "agent"
            return str(payload.id), "human"
        if has_administracion:
            return str(payload.id), "human"
        if has_agent:
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
