import asyncio

import pytest

from app.agent.nodes.handoff import create_handoff_node
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_mirror_to_chatwoot_use_case, make_ycloud_handoff_gateway
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_handoff_node_requests_handoff_and_sets_conversation_to_human():
    handoff_gateway = make_ycloud_handoff_gateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    node = create_handoff_node(handoff_gateway, conversation_repository)

    result = await node(
        make_agent_state(conversation_id="conv-1", user_message="Voy a llegar tarde")
    )

    assert result["requires_handoff"] is True
    assert "administración" in result["response_text"]
    assert handoff_gateway.handoff_requests == [
        (ConversationId("conv-1"), "Voy a llegar tarde")
    ]
    updated = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.mode == "human"
    assert updated.input_state == "HUMAN"


@pytest.mark.asyncio
async def test_handoff_node_escalates_the_conversation_to_administracion_in_chatwoot():
    handoff_gateway = make_ycloud_handoff_gateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="agent")
    )
    chatwoot_gateway = FakeChatwootGateway()
    mirror_to_chatwoot = make_mirror_to_chatwoot_use_case(chatwoot_gateway)
    node = create_handoff_node(handoff_gateway, conversation_repository, mirror_to_chatwoot)

    await node(
        make_agent_state(
            conversation_id="ycloud-+5491122334455", user_message="Necesito hablar con alguien"
        )
    )
    await asyncio.sleep(0.05)  # let the fire-and-forget mirror task run

    assert list(chatwoot_gateway.labels_by_conversation.values()) == ["administracion"]


@pytest.mark.asyncio
async def test_handoff_node_still_escalates_locally_when_the_chatwoot_mirror_fails():
    # Regla de oro: a broken Chatwoot mirror must never affect the real
    # handoff to a human.
    handoff_gateway = make_ycloud_handoff_gateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="agent")
    )
    mirror_to_chatwoot = make_mirror_to_chatwoot_use_case(FakeChatwootGateway(fail=True))
    node = create_handoff_node(handoff_gateway, conversation_repository, mirror_to_chatwoot)

    result = await node(
        make_agent_state(
            conversation_id="ycloud-+5491122334455", user_message="Necesito hablar con alguien"
        )
    )
    await asyncio.sleep(0.05)

    assert result["requires_handoff"] is True
    updated = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert updated is not None
    assert updated.mode == "human"
