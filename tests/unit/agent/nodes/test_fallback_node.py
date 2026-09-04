import pytest

from app.agent.nodes.fallback import fallback_node
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
)
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_fallback_node_shows_the_main_menu_as_buttons():
    result = await fallback_node(make_agent_state(user_message="asdkjaslkdj"))

    buttons = result["response_buttons"]
    assert [button.id for button in buttons] == [
        MENU_APPOINTMENT_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    ]
    assert [button.title for button in buttons] == ["Turnos", "Especialidades", "Administración"]
    assert result["requires_handoff"] is False
