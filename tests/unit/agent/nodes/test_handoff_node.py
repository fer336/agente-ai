import asyncio

import pytest

from app.agent.nodes.handoff import HANDOFF_ACK_MESSAGES, create_handoff_node
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
    assert "asesor" in result["response_text"]
    assert "administración" not in result["response_text"].lower()
    assert handoff_gateway.handoff_requests == [
        (ConversationId("conv-1"), "Voy a llegar tarde")
    ]
    updated = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.mode == "human"
    assert updated.input_state == "HUMAN"


def test_there_are_several_distinct_handoff_acknowledgements():
    assert len(HANDOFF_ACK_MESSAGES) >= 5
    assert len(set(HANDOFF_ACK_MESSAGES)) == len(HANDOFF_ACK_MESSAGES)


@pytest.mark.parametrize("message", HANDOFF_ACK_MESSAGES)
def test_every_handoff_acknowledgement_promises_the_same_things(message):
    lowered = message.lower()
    assert "asesor" in lowered
    assert "en breve" in lowered
    assert "este mismo chat" in lowered
    # The patient is told the assistant steps aside so the team can take over.
    assert "paus" in lowered
    # The patient never sees the internal word, see the first node test.
    assert "administración" not in lowered
    assert len(message) <= 400


@pytest.mark.asyncio
async def test_handoff_node_replies_with_the_variant_picked_by_the_chooser():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    node = create_handoff_node(
        make_ycloud_handoff_gateway(),
        conversation_repository,
        choose_message=lambda options: options[2],
    )

    result = await node(make_agent_state(conversation_id="conv-1", user_message="Hola"))

    assert result["response_text"] == HANDOFF_ACK_MESSAGES[2]
    assert result["requires_handoff"] is True


@pytest.mark.asyncio
async def test_handoff_node_does_not_always_reply_the_same_text_by_default():
    seen: set[str] = set()
    for index in range(60):
        conversation_repository = FakeConversationRepository()
        await conversation_repository.save(make_conversation(id_=f"conv-{index}", mode="agent"))
        node = create_handoff_node(make_ycloud_handoff_gateway(), conversation_repository)
        result = await node(make_agent_state(conversation_id=f"conv-{index}", user_message="Hola"))
        seen.add(result["response_text"])

    assert seen <= set(HANDOFF_ACK_MESSAGES)
    assert len(seen) > 1


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
