from dataclasses import dataclass, field

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass(frozen=True, slots=True)
class AdReferralDTO:
    """Click-to-WhatsApp ad data Meta attaches to the first message of a lead.

    Vendor-neutral view of the webhook's `referral` object: the fields we
    attribute on, plus the bounded raw object so nothing is lost while the
    real payload shape is still being learned.
    """

    source_id: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    headline: str | None = None
    body: str | None = None
    ctwa_clid: str | None = None
    media_type: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


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

    `profile_name` is the sender's WhatsApp profile name when the vendor
    reports one, used to name the contact in Chatwoot; `None` otherwise.

    `referral` is the Click-to-WhatsApp ad data, present only on the first
    message of a lead that clicked an ad.
    """

    external_message_id: str
    from_phone: PhoneNumber
    text: str
    button_payload: str | None = None
    message_type: str = "text"
    media_id: str | None = None
    media_mime_type: str | None = None
    media_sha256: str | None = None
    profile_name: str | None = None
    referral: AdReferralDTO | None = None
