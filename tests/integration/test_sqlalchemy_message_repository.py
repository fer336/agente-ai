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
