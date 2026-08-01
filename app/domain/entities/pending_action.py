from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId


@dataclass
class PendingAction:
    """Minimal pending action shell, sized to type gateway Protocol signatures."""

    id: str
    conversation_id: ConversationId
    action_type: str
    payload: dict[str, object]
    confirmation_token: ConfirmationToken
    status: str
    expires_at: datetime
