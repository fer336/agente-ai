from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.entities.message import Message
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.infrastructure.database.repositories.message_repository import SqlAlchemyMessageRepository


async def test_save_persists_a_message(db_session, conversation_id):
    repository = SqlAlchemyMessageRepository(db_session)
    message = Message(
        id="msg-1",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-1"),
        direction="inbound",
        text="hola",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    await repository.save(message)

    assert await repository.exists_by_external_id(ExternalMessageId(value="wamid-1")) is True


async def test_exists_by_external_id_returns_false_when_missing(db_session):
    repository = SqlAlchemyMessageRepository(db_session)

    assert await repository.exists_by_external_id(ExternalMessageId(value="unknown")) is False


async def test_save_rejects_duplicate_external_message_id(db_session, conversation_id):
    repository = SqlAlchemyMessageRepository(db_session)
    created_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    message = Message(
        id="msg-2",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-2"),
        direction="inbound",
        text="hola",
        created_at=created_at,
    )
    await repository.save(message)

    duplicate = Message(
        id="msg-3",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-2"),
        direction="inbound",
        text="hola de nuevo",
        created_at=created_at,
    )

    with pytest.raises(IntegrityError):
        await repository.save(duplicate)


async def test_save_persists_audio_media_fields(db_session, conversation_id):
    repository = SqlAlchemyMessageRepository(db_session)
    created_at = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    message = Message(
        id="msg-audio-1",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-audio-1"),
        direction="inbound",
        text="",
        created_at=created_at,
        message_type="audio",
        media_id="media-1",
        media_mime_type="audio/ogg",
        media_status="pending",
        inbound_received_at=created_at,
    )

    await repository.save(message)
    fetched = await repository.get_by_id("msg-audio-1")

    assert fetched is not None
    assert fetched.message_type == "audio"
    assert fetched.media_id == "media-1"
    assert fetched.media_mime_type == "audio/ogg"
    assert fetched.media_status == "pending"


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyMessageRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_update_persists_transcription_result(db_session, conversation_id):
    repository = SqlAlchemyMessageRepository(db_session)
    created_at = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    message = Message(
        id="msg-audio-2",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-audio-2"),
        direction="inbound",
        text="",
        created_at=created_at,
        message_type="audio",
        media_id="media-2",
        media_mime_type="audio/ogg",
        media_status="pending",
    )
    await repository.save(message)

    transcribed = Message(
        id="msg-audio-2",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-audio-2"),
        direction="inbound",
        text="hola quiero un turno",
        created_at=created_at,
        message_type="audio",
        media_id="media-2",
        media_mime_type="audio/ogg",
        media_status="completed",
        transcription="hola quiero un turno",
        transcription_status="completed",
        transcription_provider="groq",
        transcription_model="whisper-large-v3-turbo",
        transcription_duration_ms=850,
    )
    await repository.update(transcribed)

    fetched = await repository.get_by_id("msg-audio-2")
    assert fetched is not None
    assert fetched.text == "hola quiero un turno"
    assert fetched.media_status == "completed"
    assert fetched.transcription_status == "completed"
    assert fetched.transcription_provider == "groq"
    assert fetched.transcription_duration_ms == 850


async def test_update_raises_when_message_does_not_exist(db_session, conversation_id):
    repository = SqlAlchemyMessageRepository(db_session)
    missing = Message(
        id="msg-missing",
        conversation_id=ConversationId(value=conversation_id),
        external_message_id=ExternalMessageId(value="wamid-missing"),
        direction="inbound",
        text="",
        created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        await repository.update(missing)


async def test_get_by_conversation_id_returns_only_matching_messages_oldest_first(
    db_session, conversation_id, contact_id
):
    from app.infrastructure.database.models.conversation import ConversationModel

    other_conversation = ConversationModel(id="conv-other", contact_id=contact_id, mode="agent")
    db_session.add(other_conversation)
    await db_session.flush()

    repository = SqlAlchemyMessageRepository(db_session)
    await repository.save(
        Message(
            id="msg-second",
            conversation_id=ConversationId(value=conversation_id),
            external_message_id=ExternalMessageId(value="wamid-second"),
            direction="inbound",
            text="segundo",
            created_at=datetime(2026, 8, 20, 9, 5, tzinfo=UTC),
        )
    )
    await repository.save(
        Message(
            id="msg-first",
            conversation_id=ConversationId(value=conversation_id),
            external_message_id=ExternalMessageId(value="wamid-first"),
            direction="inbound",
            text="primero",
            created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )
    )
    await repository.save(
        Message(
            id="msg-other-conv",
            conversation_id=ConversationId(value="conv-other"),
            external_message_id=ExternalMessageId(value="wamid-other"),
            direction="inbound",
            text="otro",
            created_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )
    )

    fetched = await repository.get_by_conversation_id(ConversationId(value=conversation_id))

    assert [m.id for m in fetched] == ["msg-first", "msg-second"]
