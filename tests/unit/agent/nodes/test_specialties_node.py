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
async def test_naming_a_specialty_with_booking_context_continues_the_booking():
    # Seen live: "Quiero un médico general" just re-printed the specialty
    # list, because this node was a read-only dead end and the doctor flow
    # only existed behind Turnos -> Sacar turno. `operation_mention="create"`
    # is what `resolve_interaction.py`'s own understanding step would have
    # carried in for genuinely explicit booking language like this.
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

    result = await node(
        make_agent_state(
            user_message="Quiero en médico general",
            collected_data={"operation_mention": "create"},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "spec-2"
    assert result["response_list"] is not None
    assert "Dra. Laura Pérez" in result["response_list"].rows[0].title
    assert "Dr. Otro" not in [r.title for r in result["response_list"].rows]


@pytest.mark.asyncio
async def test_naming_a_specialty_without_booking_context_stays_read_only():
    # Browse-vs-booking separation: the exact same specialty match, with no
    # booking intent/context at all, must show the professional list
    # without ever entering `awaiting_professional_selection` or writing
    # any booking selection field.
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

    assert "stage" not in result["collected_data"]
    assert "operation" not in result["collected_data"]
    assert "chosen_specialty_id" not in result["collected_data"]
    assert "chosen_professional_id" not in result["collected_data"]
    assert result["response_list"] is not None
    assert "Dra. Laura Pérez" in result["response_list"].rows[0].title


@pytest.mark.asyncio
async def test_naming_a_professional_with_booking_context_skips_the_specialty_question():
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
        make_agent_state(
            user_message="Quiero un turno con el doctor Carlos adahenao",
            collected_data={"operation_mention": "create"},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "spec-1"
    assert result["response_list"] is not None
    assert "Carlos Adahenao" in result["response_list"].rows[0].title
    assert "Camila Carasatorre" not in [r.title for r in result["response_list"].rows]


@pytest.mark.asyncio
async def test_naming_a_professional_without_booking_context_stays_read_only():
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

    assert "stage" not in result["collected_data"]
    assert "operation" not in result["collected_data"]
    assert "chosen_specialty_id" not in result["collected_data"]
    assert result["response_list"] is not None
    assert "Carlos Adahenao" in result["response_list"].rows[0].title


@pytest.mark.asyncio
async def test_active_appointment_stage_counts_as_booking_context():
    # A temporary informational detour into this node (`resolve_interaction`
    # routing intent="specialties" while an appointment stage is active,
    # design's "must not clear collected_data['stage']" rule) still counts
    # as real booking context — an already in-flight booking is not a
    # fresh browse.
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )

    result = await node(
        make_agent_state(
            user_message="Quiero ortodoncia",
            collected_data={"stage": "awaiting_slot_selection"},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION


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
