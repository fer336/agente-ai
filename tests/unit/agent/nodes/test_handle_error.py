import pytest

from app.agent.nodes.handle_error import handle_error_node
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_handle_error_node_returns_a_safe_fallback_message():
    result = await handle_error_node(make_agent_state(error="agreement"))

    assert result["response_text"]
    assert "problema técnico" in result["response_text"]


@pytest.mark.asyncio
async def test_handle_error_node_clears_the_error_field():
    result = await handle_error_node(make_agent_state(error="agreement"))

    assert result["error"] is None


@pytest.mark.asyncio
async def test_handle_error_node_does_not_request_handoff_by_default():
    result = await handle_error_node(make_agent_state(error="agreement"))

    assert result["requires_handoff"] is False
