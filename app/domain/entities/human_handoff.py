from dataclasses import dataclass

from app.domain.value_objects.conversation_id import ConversationId


@dataclass
class HumanHandoff:
    """Minimal human handoff shell, sized to type gateway Protocol signatures."""

    id: str
    conversation_id: ConversationId
    reason: str
    status: str
