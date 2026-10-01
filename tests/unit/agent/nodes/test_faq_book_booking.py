"""Booking a consulta particular: the "General" specialty is preselected and its soonest
slots are shown directly, after the first-visit question and without the specialty list."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.clinic_topics import PRESELECTED_SPECIALTY_KEY
from app.agent.first_visit_intake_subgraph import FIRST_VISIT_CANCEL_PAYLOAD
from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.agent.nodes.appointment_selection import STAGE_AWAITING_SLOT_SELECTION
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.menu_payloads import MENU_MAIN_PAYLOAD
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation
from tests.fixtures.gateways import (
    make_conversation_repository,
    make_dentalink_gateway,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import make_conversation, make_professional, make_specialty

_BOOK = "FAQ_BOOK:consulta_particular"
_PATIENT = {
    "id": "pat-1",
    "full_name": "Juan Perez",
    "phone": "+5491122334455",
    "dni": "30123456",
}


def _slot(id_: str, professional_id: str, specialty_id: str, days: int = 1) -> AppointmentSlot:
    start = datetime.now(UTC) + timedelta(days=days)
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id=specialty_id,
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


def _general_world(general_name: str = "General"):
    """General and 'Odontología general' both staffed, each with its own slot."""
    return {
        "specialties": [
            make_specialty(id_="odo", name="Odontología general"),
            make_specialty(id_="gen", name=general_name),
        ],
        "professionals": [
            make_professional(id_="prof-odo", specialty_id="odo"),
            make_professional(id_="prof-gen", specialty_id="gen"),
        ],
        "available_slots": [
            _slot("slot-odo", "prof-odo", "odo"),
            _slot("slot-gen", "prof-gen", "gen", days=2),
        ],
    }


async def _subgraph(world):
    repository = make_conversation_repository()
    await repository.save(make_conversation(id_="conv-1", mode="agent"))
    return build_appointment_decision_graph(
        appointment_gateway=make_dentalink_gateway(
            available_slots=world["available_slots"], professionals=world["professionals"]
        ),
        specialty_gateway=make_specialty_gateway(specialties=world["specialties"]),
        conversation_repository=repository,
        llm_provider=FakeLLMProvider(),
    )


def _decision_state(**data):
    return {
        "conversation_id": "conv-1",
        "user_message": "",
        "button_payload": None,
        "recent_messages": [],
        "contact_memory_summary": None,
        "pending_action_id": None,
        "collected_data": {
            "operation": CREATE_APPOINTMENT_ACTION,
            PRESELECTED_SPECIALTY_KEY: "General",
            **data,
        },
    }


def _row_ids(result) -> list[str]:
    return [row.id for row in result["response_list"].rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["General", "GENERAL", "  general ", "Géneral"])
async def test_the_general_specialty_slots_are_shown_instead_of_the_specialty_list(name):
    graph = await _subgraph(_general_world(general_name=name))

    result = await graph.ainvoke(_decision_state())

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["chosen_specialty_id"] == "gen"
    assert data["chosen_specialty_name"] == name
    assert [slot.id for slot in data["available_slots"]] == ["slot-gen"]
    assert _row_ids(result)[0] == "SELECT_SLOT:slot-gen"
    assert not any(row_id.startswith("SPECIALTY:") for row_id in _row_ids(result))
    assert PRESELECTED_SPECIALTY_KEY not in data


@pytest.mark.asyncio
async def test_odontologia_general_is_never_taken_for_general(caplog):
    world = _general_world()
    world["specialties"] = [make_specialty(id_="odo", name="Odontología general")]
    graph = await _subgraph(world)

    with caplog.at_level(logging.WARNING):
        result = await graph.ainvoke(_decision_state())

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert "chosen_specialty_id" not in data
    assert PRESELECTED_SPECIALTY_KEY not in data
    assert any("General" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_general_specialty_without_slots_falls_back_to_the_specialty_list():
    world = _general_world()
    world["available_slots"] = [_slot("slot-odo", "prof-odo", "odo")]
    graph = await _subgraph(world)

    result = await graph.ainvoke(_decision_state())

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert any(row_id.startswith("SPECIALTY:") for row_id in _row_ids(result))
    assert PRESELECTED_SPECIALTY_KEY not in data


@pytest.mark.asyncio
async def test_a_general_specialty_without_professionals_falls_back_to_the_list():
    world = _general_world()
    world["professionals"] = [make_professional(id_="prof-odo", specialty_id="odo")]
    graph = await _subgraph(world)

    result = await graph.ainvoke(_decision_state())

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert PRESELECTED_SPECIALTY_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_without_the_key_the_normal_specialty_list_is_shown():
    graph = await _subgraph(_general_world())
    state = _decision_state()
    del state["collected_data"][PRESELECTED_SPECIALTY_KEY]

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


async def _node(**world_overrides):
    world = {**_general_world(), **world_overrides}
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
    )
    return node


@pytest.mark.asyncio
async def test_a_new_patient_still_gets_the_first_visit_question_first_and_the_key_survives():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload=_BOOK,
            user_message="Agendar cita",
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"
    assert result["response_buttons"] is not None


@pytest.mark.asyncio
async def test_after_the_intake_the_patient_lands_on_the_general_slots():
    node = await _node()
    question = await node(
        make_agent_state(
            button_payload=_BOOK,
            collected_data={
                PRESELECTED_SPECIALTY_KEY: "General",
                "identification_full_name": "Juan Perez",
                "identification_dni": "30123456",
            },
        )
    )

    result = await node(
        make_agent_state(
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD,
            collected_data=question["collected_data"],
        )
    )

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["chosen_specialty_name"] == "General"
    assert PRESELECTED_SPECIALTY_KEY not in data
    assert _row_ids(result)[0] == "SELECT_SLOT:slot-gen"


@pytest.mark.asyncio
async def test_a_remembered_patient_goes_straight_to_the_general_slots():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload=_BOOK,
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
            patient_identity=_PATIENT,
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "gen"
    assert PRESELECTED_SPECIALTY_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_mid_flow_book_tap_restarts_the_create_flow_on_the_general_slots():
    node = await _node()
    stale = {
        "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
        "operation": CREATE_APPOINTMENT_ACTION,
        "chosen_specialty_id": "odo",
        "chosen_specialty_name": "Odontología general",
        PRESELECTED_SPECIALTY_KEY: "General",
    }

    result = await node(
        make_agent_state(
            button_payload=_BOOK,
            collected_data=stale,
            patient_identity=_PATIENT,
        )
    )

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["chosen_specialty_id"] == "gen"
    assert [slot.id for slot in data["available_slots"]] == ["slot-gen"]


@pytest.mark.asyncio
async def test_the_key_does_not_leak_into_a_later_booking():
    node = await _node()
    first = await node(
        make_agent_state(
            button_payload=_BOOK,
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
            patient_identity=_PATIENT,
        )
    )
    assert PRESELECTED_SPECIALTY_KEY not in first["collected_data"]

    # Later booking from the welcome menu: the specialty list, not General.
    second = await node(
        make_agent_state(
            button_payload="OPERATION_CREATE",
            collected_data={},
            patient_identity=_PATIENT,
        )
    )

    assert second["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


@pytest.mark.asyncio
async def test_a_main_menu_tap_clears_the_key():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload=MENU_MAIN_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_FIRST_VISIT_INTAKE,
                PRESELECTED_SPECIALTY_KEY: "General",
            },
        )
    )

    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_a_missing_general_falls_back_to_the_specialty_list_at_node_level():
    node = await _node(specialties=[make_specialty(id_="odo", name="Odontología general")])

    result = await node(
        make_agent_state(
            button_payload=_BOOK,
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
            patient_identity=_PATIENT,
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert PRESELECTED_SPECIALTY_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_non_booking_operation_drops_the_key():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload="OPERATION_CANCEL",
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
        )
    )

    assert PRESELECTED_SPECIALTY_KEY not in result["collected_data"]
