from dataclasses import dataclass

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass(frozen=True, slots=True)
class InboundMessageDTO:
    """Vendor-neutral inbound message, parsed from a YCloud webhook payload.

    Crossing this boundary is deliberate: `app/application` and `app/domain`
    stay blind to YCloud's raw JSON shape (see
    `app/infrastructure/ycloud/webhook_parser.py`). There is no separate
    conversation-id field: WhatsApp conversations are 1:1 with the sender's
    phone number, so `IngestMessageUseCase` derives the internal
    `ConversationId` from `from_phone` directly.

    `button_payload` carries the machine-readable id of a tapped interactive
    button (PRD.md §6: "Botón -> Intención conocida") when the inbound
    message is a button reply, `None` for free text/audio. `text` is always
    populated with a human-readable representation (the button's title for
    a button reply) so callers that only care about display text never need
    to special-case `button_payload is not None`.

    `message_type="audio"` (PRD.md §24.1) carries no `text` yet — it is
    filled in later, once `TranscribeAudioUseCase` produces a transcript —
    and instead carries the vendor's opaque `media_id`/`media_mime_type`
    (+ optional `media_sha256`) needed to resolve and download the file.
    """

    external_message_id: str
    from_phone: PhoneNumber
    text: str
    button_payload: str | None = None
    message_type: str = "text"
    media_id: str | None = None
    media_mime_type: str | None = None
    media_sha256: str | None = None
