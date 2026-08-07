import pytest

from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


def test_fake_conversation_repository_satisfies_conversation_repository_protocol():
    assert isinstance(FakeConversationRepository(), ConversationRepository)


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = FakeConversationRepository()

    assert await repository.get_by_id(ConversationId("chatwoot-100")) is None


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = FakeConversationRepository()
    conversation = make_conversation(id_="chatwoot-100")

    await repository.save(conversation)
    fetched = await repository.get_by_id(ConversationId("chatwoot-100"))

    assert fetched == conversation
