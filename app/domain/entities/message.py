from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId


@dataclass
class Message:
    """Minimal message shell, sized to type gateway Protocol signatures."""

    id: str
    conversation_id: ConversationId
    external_message_id: ExternalMessageId
    direction: str
    text: str
    created_at: datetime
