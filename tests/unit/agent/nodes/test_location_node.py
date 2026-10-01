import pytest

from app.agent.nodes.location import asks_for_location, create_location_node, location_node
from app.domain.value_objects.menu_payloads import LOCATION_DETAIL_PAYLOAD, MENU_LOCATION_PAYLOAD
from tests.fixtures.agent_state import make_agent_state

_IMAGE_URL = "https://agent.example.com/public/clinic-location.jpg"


def test_location_detection_is_deterministic():
    assert asks_for_location("Hola, cómo llegar a la clínica?") is True
    assert asks_for_location("quiero un turno") is False


@pytest.mark.asyncio
async def test_location_node_without_an_image_url_returns_the_native_location_card():
    result = await location_node(make_agent_state())

    location = result["response_location"]
    assert location is not None
    assert location.name == "Smiling Pilar"
    assert location.address == "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"
    assert result.get("response_image_url") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_overrides",
    [
        {"user_message": "dónde queda la clínica"},
        {"user_message": "📍 Cómo llegar", "button_payload": MENU_LOCATION_PAYLOAD},
    ],
)
async def test_location_node_sends_the_image_with_a_how_to_arrive_button(state_overrides):
    node = create_location_node(_IMAGE_URL)

    result = await node(make_agent_state(**state_overrides))

    assert result["response_image_url"] == _IMAGE_URL
    assert result["response_location"] is None
    assert result["requires_handoff"] is False
    caption = result["response_text"]
    assert isinstance(caption, str)
    assert 0 < len(caption) <= 300
    assert "Las Camelias 3324" in caption
    buttons = result["response_buttons"]
    assert [(b.id, b.title) for b in buttons] == [(LOCATION_DETAIL_PAYLOAD, "Cómo llegar")]


@pytest.mark.asyncio
async def test_tapping_the_how_to_arrive_button_returns_the_native_location_card():
    node = create_location_node(_IMAGE_URL)

    result = await node(make_agent_state(button_payload=LOCATION_DETAIL_PAYLOAD))

    location = result["response_location"]
    assert location is not None
    assert location.name == "Smiling Pilar"
    assert result["response_text"] is None
    assert result["response_buttons"] is None
    assert result["response_image_url"] is None


@pytest.mark.asyncio
async def test_location_node_never_touches_the_workflow_data():
    node = create_location_node(_IMAGE_URL)

    result = await node(make_agent_state(collected_data={"stage": "awaiting_slot_selection"}))

    assert "collected_data" not in result
