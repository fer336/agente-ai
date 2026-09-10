import pytest

from app.agent.nodes.location import asks_for_location, location_node
from tests.fixtures.agent_state import make_agent_state


def test_location_detection_is_deterministic():
    assert asks_for_location("Hola, cómo llegar a la clínica?") is True
    assert asks_for_location("quiero un turno") is False


@pytest.mark.asyncio
async def test_location_node_returns_verified_native_location():
    result = await location_node(make_agent_state())

    location = result["response_location"]
    assert location is not None
    assert location.name == "Smiling Pilar"
    assert location.address == "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"
