"""The frequent topic the patient chose is remembered (like the aligner option) until the
booking is confirmed, and then it is gone: `BOOKING_TOPIC_KEY` lifecycle."""

import pytest

from app.agent.clinic_topics import (
    ALIGNER_OPTION_KEY,
    BOOKING_TOPIC_KEY,
    PRESELECTED_SPECIALTY_KEY,
)
from app.agent.first_visit_intake_subgraph import FIRST_VISIT_CANCEL_PAYLOAD
from app.agent.nodes.appointment import (
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.agent.nodes.appointment_selection import STAGE_AWAITING_SLOT_SELECTION
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import UnderstandingResult
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import confirm_identification, make_node_and_conversation
from tests.fixtures.gateways import make_proposal_repositories_provider
from tests.unit.agent.nodes.test_faq_book_booking import _PATIENT, _general_world


class _BookingLLM(FakeLLMProvider):
    async def understand(self, message, context):
        return UnderstandingResult(intent="appointment", confidence=0.9, operation_mention="create")


# ---- router: the three entry points ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic_id",
    [
        "blanqueamiento",
        "consulta_particular",
        "limpieza_particular",
        "brackets_obra_social",
    ],
)
async def test_a_topic_book_tap_sets_the_topic(topic_id):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(button_payload=f"FAQ_BOOK:{topic_id}"))

    assert result["collected_data"][BOOKING_TOPIC_KEY] == topic_id


@pytest.mark.asyncio
async def test_an_alineadores_option_tap_sets_the_topic_and_keeps_the_option_key():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(button_payload="FAQ_OPTION:alineadores:2"))

    assert result["collected_data"][BOOKING_TOPIC_KEY] == "alineadores"
    assert result["collected_data"][ALIGNER_OPTION_KEY] == "2"


@pytest.mark.asyncio
async def test_a_free_text_topic_booking_sets_the_topic():
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(make_agent_state(user_message="quiero un turno para blanqueamiento"))

    assert result["collected_data"][BOOKING_TOPIC_KEY] == "blanqueamiento"


@pytest.mark.asyncio
async def test_a_free_text_booking_that_names_no_topic_sets_nothing():
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(make_agent_state(user_message="quiero un turno"))

    assert BOOKING_TOPIC_KEY not in result.get("collected_data", {})


@pytest.mark.asyncio
async def test_a_free_text_topic_booking_mid_flow_sets_nothing():
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(
        make_agent_state(
            user_message="quiero un turno para blanqueamiento",
            collected_data={"stage": "awaiting_slot_selection"},
        )
    )

    assert BOOKING_TOPIC_KEY not in result.get("collected_data", {})


@pytest.mark.asyncio
async def test_a_mid_flow_tap_replaces_the_previous_topic_and_its_option():
    node = create_resolve_interaction_node(FakeLLMProvider())
    stale = {
        "stage": "awaiting_slot_selection",
        BOOKING_TOPIC_KEY: "alineadores",
        ALIGNER_OPTION_KEY: "3",
    }

    result = await node(
        make_agent_state(button_payload="FAQ_BOOK:limpieza_particular", collected_data=stale)
    )

    assert result["collected_data"][BOOKING_TOPIC_KEY] == "limpieza_particular"
    assert ALIGNER_OPTION_KEY not in result["collected_data"]


# ---- appointment node: lifecycle ----------------------------------------------------------


async def _node():
    world = _general_world()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
    )
    return node


def _book_state(**overrides):
    base = {
        "button_payload": "FAQ_BOOK:blanqueamiento",
        "user_message": "Agendar cita",
        "collected_data": {
            PRESELECTED_SPECIALTY_KEY: "General",
            BOOKING_TOPIC_KEY: "blanqueamiento",
        },
    }
    return make_agent_state(**{**base, **overrides})


@pytest.mark.asyncio
async def test_a_new_patient_keeps_the_topic_through_the_first_visit_question():
    node = await _node()

    result = await node(_book_state())

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert data[BOOKING_TOPIC_KEY] == "blanqueamiento"


@pytest.mark.asyncio
async def test_the_topic_survives_the_intake_and_reaches_the_general_slots():
    node = await _node()
    question = await node(
        _book_state(
            collected_data={
                PRESELECTED_SPECIALTY_KEY: "General",
                BOOKING_TOPIC_KEY: "blanqueamiento",
                "identification_full_name": "Juan Perez",
                "identification_dni": "30123456",
            }
        )
    )

    shown = await node(
        make_agent_state(
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD, collected_data=question["collected_data"]
        )
    )
    result = await confirm_identification(node, shown)

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data[BOOKING_TOPIC_KEY] == "blanqueamiento"


@pytest.mark.asyncio
async def test_a_mid_flow_book_tap_keeps_the_new_topic_across_the_reset():
    node = await _node()
    stale = {
        "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
        "operation": "create_appointment",
        "chosen_specialty_id": "odo",
        PRESELECTED_SPECIALTY_KEY: "General",
        BOOKING_TOPIC_KEY: "limpieza_particular",
    }

    result = await node(_book_state(collected_data=stale, patient_identity=_PATIENT))

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data[BOOKING_TOPIC_KEY] == "limpieza_particular"


async def _proposal(node, **book_overrides):
    offered = await node(_book_state(patient_identity=_PATIENT, **book_overrides))
    return await node(
        make_agent_state(
            button_payload="SELECT_SLOT:slot-gen",
            collected_data=offered["collected_data"],
            patient_identity=_PATIENT,
        )
    )


@pytest.mark.asyncio
async def test_the_topic_reaches_the_proposal_and_its_payload_carries_the_comment():
    world = _general_world()
    provider = make_proposal_repositories_provider()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
        proposal_repositories_provider=provider,
    )

    result = await _proposal(node)

    assert result["collected_data"]["stage"] == "awaiting_confirmation"
    assert result["collected_data"][BOOKING_TOPIC_KEY] == "blanqueamiento"
    async with provider() as repos:
        pending = await repos.pending_actions.get_by_id(result["pending_action_id"])
    assert pending is not None
    assert pending.payload["comment"] == "Consulta frecuente: Blanqueamiento"


@pytest.mark.asyncio
async def test_the_payload_of_an_aligner_booking_names_the_option():
    world = _general_world()
    provider = make_proposal_repositories_provider()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
        proposal_repositories_provider=provider,
    )

    result = await _proposal(
        node,
        button_payload="FAQ_OPTION:alineadores:2",
        collected_data={
            PRESELECTED_SPECIALTY_KEY: "General",
            BOOKING_TOPIC_KEY: "alineadores",
            ALIGNER_OPTION_KEY: "2",
        },
    )

    async with provider() as repos:
        pending = await repos.pending_actions.get_by_id(result["pending_action_id"])
    assert pending is not None
    assert pending.payload["comment"] == "Consulta frecuente: Alineadores - Opción 2"


@pytest.mark.asyncio
async def test_a_booking_without_a_topic_has_no_comment_in_its_payload():
    world = _general_world()
    provider = make_proposal_repositories_provider()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
        proposal_repositories_provider=provider,
    )

    result = await _proposal(
        node,
        button_payload="FAQ_BOOK:consulta_particular",
        collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
    )

    async with provider() as repos:
        pending = await repos.pending_actions.get_by_id(result["pending_action_id"])
    assert pending is not None
    assert "comment" not in pending.payload


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["OPERATION_CANCEL", "OPERATION_RESCHEDULE", "OPERATION_VIEW"])
async def test_a_non_booking_operation_drops_the_topic(payload):
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload=payload,
            collected_data={PRESELECTED_SPECIALTY_KEY: "General", BOOKING_TOPIC_KEY: "alineadores"},
        )
    )

    assert BOOKING_TOPIC_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_main_menu_tap_clears_the_topic():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload="MENU_MAIN",
            collected_data={
                "stage": STAGE_AWAITING_FIRST_VISIT_INTAKE,
                BOOKING_TOPIC_KEY: "blanqueamiento",
            },
        )
    )

    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_a_generic_create_tap_mid_flow_does_not_keep_the_topic():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload="OPERATION_CREATE",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                BOOKING_TOPIC_KEY: "blanqueamiento",
            },
            patient_identity=_PATIENT,
        )
    )

    assert BOOKING_TOPIC_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_confirming_clears_the_topic_and_the_next_booking_carries_no_comment():
    world = _general_world()
    provider = make_proposal_repositories_provider()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
        proposal_repositories_provider=provider,
    )
    proposal = await _proposal(node)

    confirmed = await node(
        make_agent_state(
            button_payload="CONFIRM_APPOINTMENT",
            collected_data=proposal["collected_data"],
            pending_action_id=proposal["pending_action_id"],
            patient_identity=_PATIENT,
        )
    )

    assert BOOKING_TOPIC_KEY not in confirmed["collected_data"]
    assert ALIGNER_OPTION_KEY not in confirmed["collected_data"]
    next_proposal = await _proposal(
        node,
        button_payload="FAQ_BOOK:consulta_particular",
        collected_data={**confirmed["collected_data"], PRESELECTED_SPECIALTY_KEY: "General"},
    )
    async with provider() as repos:
        pending = await repos.pending_actions.get_by_id(next_proposal["pending_action_id"])
    assert pending is not None
    assert "comment" not in pending.payload


# ---- end to end: what the gateway receives -----------------------------------------------


async def _book_and_confirm(**book_overrides):
    world = _general_world()
    node, _, gateway = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
    )
    proposal = await _proposal(node, **book_overrides)
    await node(
        make_agent_state(
            button_payload="CONFIRM_APPOINTMENT",
            collected_data=proposal["collected_data"],
            pending_action_id=proposal["pending_action_id"],
            patient_identity=_PATIENT,
        )
    )
    return gateway


@pytest.mark.asyncio
async def test_a_topic_booking_reaches_the_gateway_with_its_comment():
    gateway = await _book_and_confirm()

    assert gateway.get_comment("1") == "Consulta frecuente: Blanqueamiento"


@pytest.mark.asyncio
async def test_an_alineadores_booking_reaches_the_gateway_with_the_option():
    gateway = await _book_and_confirm(
        button_payload="FAQ_OPTION:alineadores:3",
        collected_data={
            PRESELECTED_SPECIALTY_KEY: "General",
            BOOKING_TOPIC_KEY: "alineadores",
            ALIGNER_OPTION_KEY: "3",
        },
    )

    assert gateway.get_comment("1") == "Consulta frecuente: Alineadores - Opción 3"


@pytest.mark.asyncio
async def test_an_ordinary_booking_reaches_the_gateway_without_a_comment():
    gateway = await _book_and_confirm(
        button_payload="OPERATION_CREATE", collected_data={PRESELECTED_SPECIALTY_KEY: "General"}
    )

    assert gateway.get_appointment("1") is not None
    assert gateway.get_comment("1") is None
