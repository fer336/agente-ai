from datetime import UTC, datetime

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)


async def test_save_then_get_by_id_round_trips_a_conversation(db_session, contact_id):
    repository = SqlAlchemyConversationRepository(db_session)
    conversation = Conversation(
        id=ConversationId(value="conv-1"),
        contact_id=contact_id,
        mode="agent",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )

    await repository.save(conversation)
    fetched = await repository.get_by_id(ConversationId(value="conv-1"))

    assert fetched is not None
    assert fetched.contact_id == contact_id
    assert fetched.mode == "agent"
    assert fetched.input_state == "FREE_INPUT"


async def test_save_then_get_by_id_round_trips_a_custom_input_state(db_session, contact_id):
    repository = SqlAlchemyConversationRepository(db_session)
    conversation = Conversation(
        id=ConversationId(value="conv-input-state-1"),
        contact_id=contact_id,
        mode="agent",
        created_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        input_state="SENSITIVE_CONFIRMATION",
    )

    await repository.save(conversation)
    fetched = await repository.get_by_id(ConversationId(value="conv-input-state-1"))

    assert fetched is not None
    assert fetched.input_state == "SENSITIVE_CONFIRMATION"


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyConversationRepository(db_session)

    fetched = await repository.get_by_id(ConversationId(value="missing"))

    assert fetched is None


async def test_save_updates_an_existing_conversation(db_session, contact_id):
    repository = SqlAlchemyConversationRepository(db_session)
    created_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    conversation = Conversation(
        id=ConversationId(value="conv-2"),
        contact_id=contact_id,
        mode="agent",
        created_at=created_at,
    )
    await repository.save(conversation)

    conversation.mode = "human"
    await repository.save(conversation)
    fetched = await repository.get_by_id(ConversationId(value="conv-2"))

    assert fetched is not None
    assert fetched.mode == "human"
