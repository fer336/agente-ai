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
    assert result["response_list"] is not None
    assert "Dra. Laura Pérez" in result["response_list"].rows[0].title
    assert "Dr. Otro" not in [r.title for r in result["response_list"].rows]


@pytest.mark.asyncio
async def test_naming_a_professional_directly_skips_the_specialty_question():
    # Seen live: "Quiero un turno con el doctor Carlos Adahenao" kept
    # getting "Para qué especialidad querés el turno?" forever — naming a
    # professional carries no specialty name for the catalog match to
    # catch, so the mention was silently discarded.
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Implantología")],
        professionals=[
            make_professional(id_="prof-1", full_name="Carlos Adahenao", specialty_id="spec-1"),
            make_professional(id_="prof-2", full_name="Camila Carasatorre", specialty_id="spec-1"),
        ],
    )

    result = await node(
        make_agent_state(user_message="Quiero un turno con el doctor Carlos adahenao")
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "spec-1"
    assert result["response_list"] is not None
    assert "Carlos Adahenao" in result["response_list"].rows[0].title
    assert "Camila Carasatorre" not in [r.title for r in result["response_list"].rows]


@pytest.mark.asyncio
async def test_naming_an_unstaffed_specialty_falls_back_to_the_staffed_catalog():
    # "General" has zero professionals staffed, so it is excluded from the
    # catalog entirely (an unstaffed specialty is a dead end) — naming it
    # anyway must never crash or advance the stage, it just falls back to
    # whatever IS staffed.
    node = _node(
        specialties=[
            make_specialty(id_="spec-1", name="Ortodoncia"),
            make_specialty(id_="spec-2", name="General"),
        ],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="spec-1"),
        ],
    )

    result = await node(make_agent_state(user_message="quiero general"))

    assert result["response_list"] is not None
    assert "Ortodoncia" in result["response_list"].rows[0].title
    assert "General" not in [r.title for r in result["response_list"].rows]
    assert result["collected_data"] == {"specialties_page": 0}


@pytest.mark.asyncio
async def test_lists_every_configured_specialty():
    node = _node(
        specialties=[
            make_specialty(id_="spec-1", name="Ortodoncia"),
            make_specialty(id_="spec-2", name="Endodoncia"),
        ],
        professionals=[
            make_professional(id_="prof-1", specialty_id="spec-1"),
            make_professional(id_="prof-2", specialty_id="spec-2"),
        ],
    )

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert result["response_list"] is not None
    assert "Ortodoncia" in result["response_list"].rows[0].title
    assert "Endodoncia" in result["response_list"].rows[1].title
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_never_crashes_on_an_empty_catalog():
    node = _node(specialties=[])

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert "no tenemos especialidades" in result["response_text"]
    assert result["requires_handoff"] is False
