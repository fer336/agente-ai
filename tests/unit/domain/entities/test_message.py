from datetime import UTC, datetime

from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId


def test_creates_message_with_all_fields():
    message = Message(
        id="msg-1",
        conversation_id=ConversationId(value="conv-1"),
        external_message_id=ExternalMessageId(value="wamid-1"),
        direction="inbound",
        text="Hola, queria consultar por un turno",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    assert message.id == "msg-1"
    assert message.external_message_id == ExternalMessageId(value="wamid-1")
    assert message.direction == "inbound"


def test_messages_with_different_direction_are_not_equal():
    created_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    first = Message(
        id="msg-2",
        conversation_id=ConversationId(value="conv-2"),
        external_message_id=ExternalMessageId(value="wamid-2"),
        direction="inbound",
        text="hola",
        created_at=created_at,
    )
    second = Message(
        id="msg-2",
        conversation_id=ConversationId(value="conv-2"),
        external_message_id=ExternalMessageId(value="wamid-2"),
        direction="outbound",
        text="hola",
        created_at=created_at,
    )

    assert first != second
