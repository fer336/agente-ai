from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryFailureDTO:
    """Vendor-neutral WhatsApp delivery failure, parsed from a YCloud
    `whatsapp.message.updated` webhook payload (see
    `app/infrastructure/ycloud/webhook_parser.py`).

    `message_id` is the SAME external message id `MessagingGateway.send_*`
    returned at send time — the only reliable key to resolve which
    conversation this failure belongs to (see
    `app.domain.entities.sent_message.SentMessage`).
    """

    message_id: str
    error_code: str
    error_message: str
    technical_detail: str
