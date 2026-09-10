from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey


@dataclass
class ScheduledAction:
    """Minimal scheduled action shell, sized to type repository Protocol signatures."""

    id: str
    conversation_id: ConversationId
    #: `None` for a follow-up scheduled BEFORE any `PendingAction` exists —
    #: a patient stuck mid-flow (e.g. still typing their DNI) has nothing
    #: to confirm yet. Only the original `appointment_confirmation_timeout`
    #: `action_type` requires one.
    pending_action_id: str | None
    action_type: str
    status: str
    scheduled_for: datetime
    idempotency_key: IdempotencyKey
    attempts: int
    workflow_generation: int = 1
