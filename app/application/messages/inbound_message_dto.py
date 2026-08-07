from dataclasses import dataclass

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass(frozen=True, slots=True)
class InboundMessageDTO:
    """Vendor-neutral inbound message, parsed from a Chatwoot webhook payload.

    Crossing this boundary is deliberate: `app/application` and `app/domain`
    stay blind to Chatwoot's raw JSON shape (see
    `app/infrastructure/chatwoot/webhook_payload.py`).
    """

    external_message_id: str
    chatwoot_conversation_id: str
    from_phone: PhoneNumber
    text: str
