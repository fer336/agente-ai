import pytest

from app.agent.nodes.fallback import fallback_node
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_fallback_node_shows_the_main_menu():
    result = await fallback_node(make_agent_state(user_message="asdkjaslkdj"))

    assert "Turnos" in result["response_text"]
    assert "Obras sociales" in result["response_text"]
    assert "Administración" in result["response_text"]
    assert result["requires_handoff"] is False
