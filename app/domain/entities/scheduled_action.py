from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey


@dataclass
class ScheduledAction:
    """Minimal scheduled action shell, sized to type repository Protocol signatures."""

    id: str
    conversation_id: ConversationId
    pending_action_id: str
    action_type: str
    status: str
    scheduled_for: datetime
    idempotency_key: IdempotencyKey
    attempts: int
