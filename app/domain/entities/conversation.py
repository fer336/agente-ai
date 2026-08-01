from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId


@dataclass
class Conversation:
    """Minimal conversation shell, sized to type gateway Protocol signatures."""

    id: ConversationId
    contact_id: str
    mode: str
    created_at: datetime
