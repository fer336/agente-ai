import pytest

from app.application.conversations.chatwoot_control import PauseBotFromChatwootUseCase
from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


async def _seeded() -> tuple[
    PauseBotFromChatwootUseCase,
    FakeConversationRepository,
    FakeChatwootGateway,
]:
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    mappings = FakeChatwootMappingRepository()
    await mappings.save(
        ChatwootConversationMapping(
            conversation_id="ycloud-+5491122334455",
            chatwoot_contact_id="1",
            chatwoot_conversation_id="99",
        )
    )
    chatwoot = FakeChatwootGateway()
    return (
        PauseBotFromChatwootUseCase(chatwoot, conversations, mappings),
        conversations,
        chatwoot,
    )


@pytest.mark.asyncio
async def test_pauses_the_agent_and_sets_human_input_state():
    use_case, conversations, _ = await _seeded()

    await use_case.execute("99")

    conversation = await conversations.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "human"
    assert conversation.input_state == "HUMAN"


@pytest.mark.asyncio
async def test_optionally_syncs_the_administracion_label():
    use_case, _, chatwoot = await _seeded()

    await use_case.execute("99", synchronize_label=True)

    assert chatwoot.labels_by_conversation == {"99": "administracion"}


@pytest.mark.asyncio
async def test_no_ops_when_no_mapping_exists():
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    use_case = PauseBotFromChatwootUseCase(
        FakeChatwootGateway(), conversations, FakeChatwootMappingRepository()
    )

    await use_case.execute("does-not-exist", synchronize_label=True)

    conversation = await conversations.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_mode_flip_persists_when_label_sync_fails():
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    mappings = FakeChatwootMappingRepository()
    await mappings.save(
        ChatwootConversationMapping(
            conversation_id="ycloud-+5491122334455",
            chatwoot_contact_id="1",
            chatwoot_conversation_id="99",
        )
    )
    use_case = PauseBotFromChatwootUseCase(
        FakeChatwootGateway(fail=True), conversations, mappings
    )

    await use_case.execute("99", synchronize_label=True)

    conversation = await conversations.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.mode == "human"
