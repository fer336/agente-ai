from datetime import datetime, timezone

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_conversation_with_id_contact_mode_and_created_at():
    conversation = Conversation(
        id=ConversationId(value="conv-1"),
        contact_id="contact-1",
        mode="agent",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc),
    )

    assert conversation.id == ConversationId(value="conv-1")
    assert conversation.contact_id == "contact-1"
    assert conversation.mode == "agent"


def test_conversations_with_different_mode_are_not_equal():
    created_at = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
    first = Conversation(
        id=ConversationId(value="conv-2"),
        contact_id="contact-2",
        mode="agent",
        created_at=created_at,
    )
    second = Conversation(
        id=ConversationId(value="conv-2"),
        contact_id="contact-2",
        mode="human",
        created_at=created_at,
    )

    assert first != second
