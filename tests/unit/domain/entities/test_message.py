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


def test_defaults_to_text_message_type_with_no_media_or_transcription_fields():
    message = Message(
        id="msg-3",
        conversation_id=ConversationId(value="conv-3"),
        external_message_id=ExternalMessageId(value="wamid-3"),
        direction="inbound",
        text="hola",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    assert message.message_type == "text"
    assert message.media_id is None
    assert message.transcription is None
    assert message.transcription_status is None


def test_audio_message_carries_media_and_transcription_fields():
    message = Message(
        id="msg-4",
        conversation_id=ConversationId(value="conv-4"),
        external_message_id=ExternalMessageId(value="wamid-4"),
        direction="inbound",
        text="",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        message_type="audio",
        media_id="media-1",
        media_mime_type="audio/ogg",
        media_sha256="abc123",
        media_status="pending",
        inbound_received_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    assert message.message_type == "audio"
    assert message.media_id == "media-1"
    assert message.media_mime_type == "audio/ogg"
    assert message.media_status == "pending"
