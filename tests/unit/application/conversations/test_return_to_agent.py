import pytest

from app.application.conversations.return_to_agent import ReturnConversationToAgentUseCase
from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation

_ID = ConversationId("ycloud-+5491122334455")


async def _seeded(
    mode: str = "human",
    input_state: str = "HUMAN",
    chatwoot_gateway: FakeChatwootGateway | None = None,
    mapped: bool = True,
) -> tuple[ReturnConversationToAgentUseCase, FakeConversationRepository, FakeChatwootGateway]:
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_=str(_ID), mode=mode, input_state=input_state))
    mappings = FakeChatwootMappingRepository()
    if mapped:
        await mappings.save(
            ChatwootConversationMapping(
                conversation_id=str(_ID),
                chatwoot_contact_id="1",
                chatwoot_conversation_id="99",
            )
        )
    gateway = chatwoot_gateway or FakeChatwootGateway()
    return (
        ReturnConversationToAgentUseCase(conversations, mappings, gateway),
        conversations,
        gateway,
    )


@pytest.mark.asyncio
async def test_a_human_conversation_goes_back_to_the_agent_with_a_fresh_start():
    use_case, conversations, _ = await _seeded()

    assert await use_case.execute(_ID) is True

    conversation = await conversations.get_by_id(_ID)
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"
    assert conversation.workflow_session_generation == 2
    assert conversation.awaiting_fresh_restart is True


@pytest.mark.asyncio
async def test_the_chatwoot_label_is_swapped_back_to_agente():
    use_case, _, gateway = await _seeded()

    await use_case.execute(_ID)

    assert gateway.labels_by_conversation == {"99": "agente"}


@pytest.mark.asyncio
async def test_a_conversation_already_under_the_agent_is_left_untouched():
    use_case, conversations, gateway = await _seeded(mode="agent", input_state="FREE_INPUT")

    assert await use_case.execute(_ID) is True

    conversation = await conversations.get_by_id(_ID)
    assert conversation is not None
    assert conversation.workflow_session_generation == 1
    assert conversation.awaiting_fresh_restart is False
    assert gateway.labels_by_conversation == {}


@pytest.mark.asyncio
async def test_an_unknown_conversation_returns_false():
    use_case, _, _ = await _seeded()

    assert await use_case.execute(ConversationId("ycloud-+5490000000000")) is False


@pytest.mark.asyncio
async def test_the_mode_flip_survives_a_chatwoot_failure():
    use_case, conversations, _ = await _seeded(chatwoot_gateway=FakeChatwootGateway(fail=True))

    assert await use_case.execute(_ID) is True

    conversation = await conversations.get_by_id(_ID)
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_a_conversation_without_a_chatwoot_mapping_still_flips_and_skips_the_label():
    use_case, conversations, gateway = await _seeded(mapped=False)

    assert await use_case.execute(_ID) is True

    conversation = await conversations.get_by_id(_ID)
    assert conversation is not None
    assert conversation.mode == "agent"
    assert gateway.labels_by_conversation == {}
