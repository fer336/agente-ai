import pytest

from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_execute_updates_the_conversation_mode():
    repository = FakeConversationRepository()
    await repository.save(make_conversation(id_="conv-1", mode="agent"))
    use_case = SetConversationModeUseCase(repository)

    await use_case.execute(ConversationId("conv-1"), mode="human")

    updated = await repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.mode == "human"


@pytest.mark.asyncio
async def test_execute_preserves_contact_id_and_created_at():
    repository = FakeConversationRepository()
    original = make_conversation(id_="conv-1", contact_id="contact-9", mode="agent")
    await repository.save(original)
    use_case = SetConversationModeUseCase(repository)

    await use_case.execute(ConversationId("conv-1"), mode="human")

    updated = await repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.contact_id == "contact-9"
    assert updated.created_at == original.created_at


@pytest.mark.asyncio
async def test_execute_raises_when_conversation_does_not_exist():
    repository = FakeConversationRepository()
    use_case = SetConversationModeUseCase(repository)

    with pytest.raises(ValueError, match="not found"):
        await use_case.execute(ConversationId("missing"), mode="human")
