import pytest

from app.agent.nodes.specialties import create_specialties_node
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_specialty_gateway
from tests.fixtures.seed_objects import make_specialty


@pytest.mark.asyncio
async def test_lists_every_configured_specialty():
    gateway = make_specialty_gateway(
        specialties=[
            make_specialty(id_="spec-1", name="Ortodoncia"),
            make_specialty(id_="spec-2", name="Endodoncia"),
        ]
    )
    node = create_specialties_node(gateway)

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert "Ortodoncia" in result["response_text"]
    assert "Endodoncia" in result["response_text"]
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_never_crashes_on_an_empty_catalog():
    gateway = make_specialty_gateway(specialties=[])
    node = create_specialties_node(gateway)

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert "no tenemos especialidades" in result["response_text"]
    assert result["requires_handoff"] is False
