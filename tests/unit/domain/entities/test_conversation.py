from datetime import UTC, datetime

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_conversation_with_id_contact_mode_and_created_at():
    conversation = Conversation(
        id=ConversationId(value="conv-1"),
        contact_id="contact-1",
        mode="agent",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    assert conversation.id == ConversationId(value="conv-1")
    assert conversation.contact_id == "contact-1"
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"


def test_conversation_accepts_an_explicit_input_state():
    conversation = Conversation(
        id=ConversationId(value="conv-3"),
        contact_id="contact-3",
        mode="agent",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        input_state="SENSITIVE_CONFIRMATION",
    )

    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


def test_conversations_with_different_mode_are_not_equal():
    created_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
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
