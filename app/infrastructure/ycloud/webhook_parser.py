from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.schemas import YCloudInboundEventPayload

_INBOUND_MESSAGE_EVENT_TYPE = "whatsapp.inbound_message.received"
_TEXT_MESSAGE_TYPE = "text"
_INTERACTIVE_MESSAGE_TYPE = "interactive"
_BUTTON_REPLY_TYPE = "button_reply"
_AUDIO_MESSAGE_TYPE = "audio"


def is_processable_message(payload: YCloudInboundEventPayload, whatsapp_number: str) -> bool:
    """True for a freeform text message, a button-reply interaction, or an
    audio message (PRD.md §24.1) addressed to our configured number.

    An audio message additionally needs a non-empty `audio.id` to be
    processable — a `type="audio"` payload with no usable media id has
    nothing to create a `MediaProcessingJob` for. Any other event type
    (delivery receipts, status updates, list replies, ...) is ignored.
    `whatsapp_number` filters by receiving number when configured,
    mirroring the old Chatwoot inbox-id filter for multi-number setups; an
    empty value skips that check (single-number MVP).
    """
    message = payload.whatsappInboundMessage
    if payload.type != _INBOUND_MESSAGE_EVENT_TYPE:
        return False
    if whatsapp_number and message.to != whatsapp_number:
        return False
    if message.type == _TEXT_MESSAGE_TYPE:
        return True
    if message.type == _INTERACTIVE_MESSAGE_TYPE:
        return (
            message.interactive is not None
            and message.interactive.type == _BUTTON_REPLY_TYPE
            and message.interactive.button_reply is not None
        )
    if message.type == _AUDIO_MESSAGE_TYPE:
        return message.audio is not None and bool(message.audio.id.strip())
    return False


def to_inbound_message_dto(payload: YCloudInboundEventPayload) -> InboundMessageDTO:
    """Builds the vendor-neutral DTO for an already-filtered message.

    Callers must only invoke this after confirming
    `is_processable_message()` — this function does not re-check event or
    message type. `whatsappInboundMessage.from` and `.id` have no silent
    default: a missing OR whitespace-only value raises explicitly rather
    than producing a DTO with a fabricated phone number or an empty
    `ExternalMessageId` (mirrors the Chatwoot-era parser's same invariant;
    `.strip()`-based checks because a whitespace-only string is truthy).

    A button-reply message maps `interactive.button_reply.id` to
    `button_payload` and its `.title` to `text` (a human-readable stand-in,
    e.g. for logs/transcripts) — PRD.md §6's determinism principle requires
    `resolve_interaction` to route a button turn by this known payload, not
    by re-classifying the button's title text.
    """
    message = payload.whatsappInboundMessage
    if not message.from_ or not message.from_.strip():
        raise ValueError(
            "YCloud payload whatsappInboundMessage.from is required to build InboundMessageDTO"
        )
    if not message.id.strip():
        raise ValueError(
            "YCloud payload whatsappInboundMessage.id is required to build InboundMessageDTO"
        )
    phone_value = message.from_ if message.from_.startswith("+") else f"+{message.from_}"

    if message.type == _INTERACTIVE_MESSAGE_TYPE and message.interactive is not None:
        button_reply = message.interactive.button_reply
        if button_reply is not None:
            return InboundMessageDTO(
                external_message_id=message.id,
                from_phone=PhoneNumber(phone_value),
                text=button_reply.title,
                button_payload=button_reply.id,
            )

    if message.type == _AUDIO_MESSAGE_TYPE and message.audio is not None:
        # No `text` yet (PRD.md §24.1: "No se transcribirá dentro del
        # request HTTP del webhook") — `IngestMessageUseCase` persists the
        # media metadata and creates a `MediaProcessingJob` instead of
        # scheduling the debounce/agent-invocation path immediately.
        return InboundMessageDTO(
            external_message_id=message.id,
            from_phone=PhoneNumber(phone_value),
            text="",
            button_payload=None,
            message_type="audio",
            media_id=message.audio.id,
            media_mime_type=message.audio.mime_type,
            media_sha256=message.audio.sha256,
        )

    return InboundMessageDTO(
        external_message_id=message.id,
        from_phone=PhoneNumber(phone_value),
        text=message.text.body if message.text is not None else "",
        button_payload=None,
    )
