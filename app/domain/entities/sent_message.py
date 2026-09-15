from dataclasses import dataclass
from datetime import datetime


@dataclass
class SentMessage:
    """Correlates a YCloud outbound message id to the conversation it was
    sent for.

    Exists so an async `whatsapp.message.updated` delivery-status webhook
    (sent well after the synchronous send returns — see
    `app.infrastructure.ycloud.client.YCloudClient._post_message`'s own
    docstring) can be traced back to a conversation/patient. Without this,
    a `status="failed"` event carries only YCloud's own message id and an
    opaque `recipientUserId` (NOT a phone number) — nothing to attribute
    the failure to.
    """

    id: str
    conversation_id: str
    sent_at: datetime
