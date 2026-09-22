import pytest

from app.application.conversations.reactivate_bot_from_chatwoot import (
    ReactivateBotFromChatwootUseCase,
)
from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


async def _seeded(
    chatwoot_gateway: FakeChatwootGateway | None = None,
) -> tuple[ReactivateBotFromChatwootUseCase, FakeConversationRepository, FakeChatwootGateway]:
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="human")
    )
    mapping_repository = FakeChatwootMappingRepository()
    await mapping_repository.save(
        ChatwootConversationMapping(
            conversation_id="ycloud-+5491122334455",
            chatwoot_contact_id="1",
            chatwoot_conversation_id="99",
        )
    )
    chatwoot_gateway = chatwoot_gateway or FakeChatwootGateway()
    use_case = ReactivateBotFromChatwootUseCase(
        chatwoot_gateway, conversation_repository, mapping_repository
    )
    return use_case, conversation_repository, chatwoot_gateway


@pytest.mark.asyncio
async def test_resolving_in_chatwoot_flips_the_conversation_back_to_agent_mode():
    use_case, conversation_repository, _ = await _seeded()

    await use_case.execute("99")

    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"


@pytest.mark.asyncio
async def test_resolving_in_chatwoot_resets_input_state_to_free_input():
    use_case, conversation_repository, _ = await _seeded()

    await use_case.execute("99")

    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_resolving_in_chatwoot_syncs_the_agente_label_back():
    use_case, _, chatwoot_gateway = await _seeded()

    await use_case.execute("99")

    assert chatwoot_gateway.labels_by_conversation == {"99": "agente"}


@pytest.mark.asyncio
async def test_no_ops_when_no_mapping_exists_for_the_chatwoot_conversation():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="human"))
    use_case = ReactivateBotFromChatwootUseCase(
        FakeChatwootGateway(), conversation_repository, FakeChatwootMappingRepository()
    )

    await use_case.execute("does-not-exist")

    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "human"


@pytest.mark.asyncio
async def test_mode_flip_still_persists_even_when_the_label_sync_fails():
    use_case, conversation_repository, _ = await _seeded(
        chatwoot_gateway=FakeChatwootGateway(fail=True)
    )

    await use_case.execute("99")

    conversation = await conversation_repository.get_by_id(
        ConversationId("ycloud-+5491122334455")
    )
    assert conversation is not None
    assert conversation.mode == "agent"
