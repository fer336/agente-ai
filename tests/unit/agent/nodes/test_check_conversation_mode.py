import pytest

from app.agent.nodes.check_conversation_mode import create_check_conversation_mode_node
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_returns_requires_handoff_when_conversation_is_in_human_mode():
    repository = FakeConversationRepository()
    await repository.save(make_conversation(id_="conv-1", mode="human"))
    node = create_check_conversation_mode_node(repository)

    result = await node(make_agent_state(conversation_id="conv-1"))

    assert result == {"requires_handoff": True}


@pytest.mark.asyncio
async def test_returns_empty_update_when_conversation_is_in_agent_mode():
    repository = FakeConversationRepository()
    await repository.save(make_conversation(id_="conv-1", mode="agent"))
    node = create_check_conversation_mode_node(repository)

    result = await node(make_agent_state(conversation_id="conv-1"))

    assert result == {}


@pytest.mark.asyncio
async def test_returns_empty_update_when_conversation_does_not_exist_yet():
    repository = FakeConversationRepository()
    node = create_check_conversation_mode_node(repository)

    result = await node(make_agent_state(conversation_id="conv-unknown"))

    assert result == {}
