import pytest

from app.agent.nodes.handoff import create_handoff_node
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_ycloud_handoff_gateway
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
