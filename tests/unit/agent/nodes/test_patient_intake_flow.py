"""The single intake Flow (`patient_intake_flow_id`) replaces the verification +
registration pair when configured, and its reply branches on `es_paciente`."""

import json

import pytest

from app.agent.nodes.appointment import (
    CONFIRM_APPOINTMENT_PAYLOAD,
    CREATE_APPOINTMENT_ACTION,
    REJECT_APPOINTMENT_PAYLOAD,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_REGISTRATION_FLOW,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_VERIFICATION_CONFIRMATION,
    STAGE_AWAITING_VERIFICATION_FLOW,
)
from app.domain.value_objects.flow_response import FLOW_RESPONSE_PAYLOAD_PREFIX
from app.infrastructure.ycloud.flows import PATIENT_INTAKE_FLOW_SCREEN_ID
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import future_slot
from tests.fixtures.appointment_node import make_node_and_conversation as _make_node
from tests.fixtures.seed_objects import make_patient


def _payload(**fields: str) -> str:
    return f"{FLOW_RESPONSE_PAYLOAD_PREFIX}{json.dumps(fields)}"


def _slot_selection_state(slot):
    return make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_professional_id": "prof-1",
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )


@pytest.mark.asyncio
async def test_identification_sends_one_intake_flow_instead_of_the_verification_flow():
    slot = future_slot()
    node, _, _ = await _make_node(
        available_slots=[slot],
        verification_flow_id="flow-verify",
        registration_flow_id="flow-register",
        patient_intake_flow_id="flow-intake",
    )

    result = await node(_slot_selection_state(slot))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_FLOW
    flow = result["response_flow"]
    assert flow.flow_id == "flow-intake"
    assert flow.flow_screen_id == PATIENT_INTAKE_FLOW_SCREEN_ID
    assert flow.flow_cta == "Completar datos"
    assert flow.flow_token == "conv-1"


@pytest.mark.asyncio
async def test_identification_works_with_only_the_intake_flow_configured():
    slot = future_slot()
    node, _, _ = await _make_node(available_slots=[slot], patient_intake_flow_id="flow-intake")

    result = await node(_slot_selection_state(slot))

    assert result["response_flow"].flow_id == "flow-intake"


@pytest.mark.asyncio
async def test_empty_intake_id_keeps_the_two_flow_behavior():
    slot = future_slot()
    node, _, _ = await _make_node(
        available_slots=[slot],
        verification_flow_id="flow-verify",
        registration_flow_id="flow-register",
        patient_intake_flow_id="",
    )

    result = await node(_slot_selection_state(slot))

    assert result["response_flow"].flow_id == "flow-verify"
    assert result["response_flow"].flow_cta == "Verificar"


@pytest.mark.asyncio
async def test_yes_reply_for_a_known_patient_asks_to_confirm_their_data():
    slot = future_slot()
    node, _, _ = await _make_node(
        available_slots=[slot],
        patients=[make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")],
        patient_intake_flow_id="flow-intake",
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=_payload(
            es_paciente="si", full_name="Juan Perez", dni="30123456", email="", obra_social=""
        ),
        collected_data={
            "stage": STAGE_AWAITING_VERIFICATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_CONFIRMATION
    assert result["collected_data"]["patient"]["full_name"] == "Juan Perez"
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_yes_reply_for_an_unknown_patient_resends_the_intake_flow():
    node, _, _ = await _make_node(patients=[], patient_intake_flow_id="flow-intake")
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=_payload(es_paciente="si", full_name="Nadie", dni="30999999"),
        collected_data={"stage": STAGE_AWAITING_VERIFICATION_FLOW},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_REGISTRATION_FLOW
    assert result["response_flow"].flow_id == "flow-intake"
    assert result["response_flow"].flow_screen_id == PATIENT_INTAKE_FLOW_SCREEN_ID


@pytest.mark.asyncio
async def test_no_reply_creates_the_patient_and_never_runs_the_verification_lookup():
    slot = future_slot()
    node, _, _ = await _make_node(
        available_slots=[slot],
        patients=[],
        conversation_id="ycloud-+5491122334455",
        patient_intake_flow_id="flow-intake",
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=_payload(
            es_paciente="no",
            full_name="Rosa Gomez",
            dni="30123456",
            email="rosa@example.com",
            obra_social="",
        ),
        collected_data={
            "stage": STAGE_AWAITING_VERIFICATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["patient"]["full_name"] == "Rosa Gomez"
    assert result["collected_data"]["stage"] != STAGE_AWAITING_VERIFICATION_CONFIRMATION


@pytest.mark.asyncio
async def test_no_reply_is_ignored_for_branching_when_the_intake_flow_is_not_configured():
    node, _, _ = await _make_node(patients=[], verification_flow_id="flow-verify")
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=_payload(es_paciente="no", full_name="Rosa Gomez", dni="30123456"),
        collected_data={"stage": STAGE_AWAITING_VERIFICATION_FLOW},
    )

    result = await node(state)

    # Legacy path: a verification lookup that finds nobody asks to register.
    assert result["collected_data"]["stage"] == STAGE_AWAITING_REGISTRATION_FLOW


@pytest.mark.asyncio
async def test_yes_reply_in_the_registration_stage_is_treated_as_a_verification():
    node, _, _ = await _make_node(
        patients=[make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")],
        patient_intake_flow_id="flow-intake",
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=_payload(es_paciente="si", full_name="Juan Perez", dni="30123456"),
        collected_data={"stage": STAGE_AWAITING_REGISTRATION_FLOW},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_CONFIRMATION
