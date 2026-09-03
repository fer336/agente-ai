import pytest

from app.application.conversations.sync_conversation_mode_from_tag import (
    SyncConversationModeFromTagUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_execute_resumes_the_bot_and_resets_input_state():
    messaging_gateway = FakeYCloudMessagingGateway()
    messaging_gateway.contact_phones["contact-1"] = PhoneNumber("+5491122334455")
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="human", input_state="HUMAN")
    )
    use_case = SyncConversationModeFromTagUseCase(messaging_gateway, conversation_repository)

    await use_case.execute("contact-1", "agent")

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_execute_pauses_the_bot_and_sets_human_input_state():
    messaging_gateway = FakeYCloudMessagingGateway()
    messaging_gateway.contact_phones["contact-1"] = PhoneNumber("+5491122334455")
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    use_case = SyncConversationModeFromTagUseCase(messaging_gateway, conversation_repository)

    await use_case.execute("contact-1", "human")

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "human"
    assert conversation.input_state == "HUMAN"


@pytest.mark.asyncio
async def test_execute_no_ops_when_contact_phone_cannot_be_resolved():
    messaging_gateway = FakeYCloudMessagingGateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="human"))
    use_case = SyncConversationModeFromTagUseCase(messaging_gateway, conversation_repository)

    await use_case.execute("unknown-contact", "agent")

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "human"


@pytest.mark.asyncio
async def test_execute_no_ops_when_no_conversation_exists_for_the_contact():
    messaging_gateway = FakeYCloudMessagingGateway()
    messaging_gateway.contact_phones["contact-1"] = PhoneNumber("+5491199999999")
    conversation_repository = FakeConversationRepository()
    use_case = SyncConversationModeFromTagUseCase(messaging_gateway, conversation_repository)

    await use_case.execute("contact-1", "agent")

    assert await conversation_repository.get_by_id(ConversationId("ycloud-+5491199999999")) is None
