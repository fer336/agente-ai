import pytest

from app.application.conversations.set_conversation_input_state import (
    SENSITIVE_CONFIRMATION,
    SetConversationInputStateUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_execute_updates_the_input_state():
    repository = FakeConversationRepository()
    await repository.save(make_conversation(id_="conv-1", input_state="FREE_INPUT"))
    use_case = SetConversationInputStateUseCase(repository)

    await use_case.execute(ConversationId("conv-1"), SENSITIVE_CONFIRMATION)

    updated = await repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_execute_preserves_mode_and_contact_id():
    repository = FakeConversationRepository()
    original = make_conversation(id_="conv-1", contact_id="contact-9", mode="agent")
    await repository.save(original)
    use_case = SetConversationInputStateUseCase(repository)

    await use_case.execute(ConversationId("conv-1"), SENSITIVE_CONFIRMATION)

    updated = await repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.contact_id == "contact-9"
    assert updated.mode == "agent"


@pytest.mark.asyncio
async def test_execute_raises_when_conversation_does_not_exist():
    repository = FakeConversationRepository()
    use_case = SetConversationInputStateUseCase(repository)

    with pytest.raises(ValueError, match="not found"):
        await use_case.execute(ConversationId("missing"), SENSITIVE_CONFIRMATION)
