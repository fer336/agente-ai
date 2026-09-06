import pytest

from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
)
from app.agent.nodes.specialties import create_specialties_node
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_dentalink_gateway, make_specialty_gateway
from tests.fixtures.seed_objects import make_professional, make_specialty


def _node(specialties=None, professionals=None):
    return create_specialties_node(
        make_specialty_gateway(specialties=specialties),
        make_dentalink_gateway(professionals=professionals),
    )


@pytest.mark.asyncio
async def test_naming_a_specialty_lists_its_professionals_and_continues_the_booking():
    # Seen live: "Quiero un médico general" just re-printed the specialty
    # list, because this node was a read-only dead end and the doctor flow
    # only existed behind Turnos -> Sacar turno.
    node = _node(
        specialties=[
            make_specialty(id_="spec-1", name="Ortodoncia"),
            make_specialty(id_="spec-2", name="General"),
        ],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="spec-2"),
            make_professional(id_="prof-9", full_name="Dr. Otro", specialty_id="spec-1"),
        ],
    )

    result = await node(make_agent_state(user_message="Quiero en médico general"))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "spec-2"
    assert "Dra. Laura Pérez" in result["response_text"]
    assert "Dr. Otro" not in result["response_text"]


@pytest.mark.asyncio
async def test_naming_a_specialty_with_no_professionals_still_lists_the_catalog():
    node = _node(
        specialties=[make_specialty(id_="spec-2", name="General")],
        professionals=[],
    )

    result = await node(make_agent_state(user_message="quiero general"))

    assert "General" in result["response_text"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_lists_every_configured_specialty():
    node = _node(
        specialties=[
            make_specialty(id_="spec-1", name="Ortodoncia"),
            make_specialty(id_="spec-2", name="Endodoncia"),
        ]
    )

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert "Ortodoncia" in result["response_text"]
    assert "Endodoncia" in result["response_text"]
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_never_crashes_on_an_empty_catalog():
    node = _node(specialties=[])

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert "no tenemos especialidades" in result["response_text"]
    assert result["requires_handoff"] is False
