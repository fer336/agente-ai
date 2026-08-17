import pytest

from app.agent.nodes.agreement import create_agreement_node
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_confirms_when_the_agreement_is_configured():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway)

    result = await node(make_agent_state(user_message="¿Trabajan con OSDE?"))

    assert result["response_text"] == "Sí, trabajamos con OSDE."
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_reports_not_found_when_no_configured_agreement_matches():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway)

    result = await node(make_agent_state(user_message="¿Trabajan con Swiss Medical?"))

    assert "No encontramos" in result["response_text"]


@pytest.mark.asyncio
async def test_derives_to_admin_for_coverage_amount_questions():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway)

    result = await node(
        make_agent_state(user_message="¿Cuánto me cubre OSDE en una corona?")
    )

    assert result["response_text"] == (
        "Esta consulta necesita ser revisada por administración.\n"
        "¿Querés que te comunique con ellos?"
    )


@pytest.mark.asyncio
async def test_never_invents_a_match_for_an_unconfigured_agreement_percentage_question():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway)

    result = await node(
        make_agent_state(user_message="¿Qué porcentaje cubre Swiss Medical?")
    )

    assert "No encontramos" in result["response_text"]
