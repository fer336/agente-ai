"""Steps that send buttons, a list or a Flow show their fixed text, never model wording.

Live bug: `gemini-3.5-flash-lite` improvised above buttons and lists (greetings, a symptoms
disclaimer, administration offers, "He registrado tu solicitud"). Every test here uses a model
that ignores its instructions and answers off-script: the text the patient sees must still be
the constant the step passes as its fixed text.
"""

import pytest

import app.agent.appointment_decision_subgraph as subgraph
from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.nodes import appointment as node_module
from app.agent.nodes.appointment import (
    _CONFIRM_BUTTONS,
    _CONFIRMATION_REMINDER,
    _MAIN_MENU_RESET_MESSAGE,
    _NO_APPOINTMENTS_MESSAGE,
    _SEND_INTAKE_FLOW_MESSAGE,
    _SEND_REGISTRATION_FLOW_MESSAGE,
    _SEND_VERIFICATION_FLOW_MESSAGE,
    _STALE_TAP_MESSAGE,
    CANCEL_APPOINTMENT_ACTION,
    CONFIRM_APPOINTMENT_PAYLOAD,
    CREATE_APPOINTMENT_ACTION,
    RESCHEDULE_APPOINTMENT_ACTION,
    SELECT_APPOINTMENT_PAYLOAD_PREFIX,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_APPOINTMENT_SELECTION,
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    STAGE_AWAITING_VERIFICATION_FLOW,
)
from app.domain.value_objects.flow_response import FLOW_RESPONSE_PAYLOAD_PREFIX
from app.domain.value_objects.menu_payloads import (
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import (
    confirm_identification,
    future_slot,
    identify_and_confirm,
    make_node_and_conversation,
)
from tests.fixtures.gateways import (
    make_conversation_repository,
    make_dentalink_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import (
    make_conversation,
    make_patient,
    make_pending_action,
    make_professional,
    make_specialty,
)

_OFF_SCRIPT = "Con gusto te ayudo. Querés que agendemos un turno o te paso con administración?"
_PATIENT = {
    "id": "pat-1",
    "full_name": "Juan Perez",
    "phone": "+5491122334455",
    "dni": "30123456",
}


class _ImprovisingLLM(FakeLLMProvider):
    """A model that ignores every instruction and answers off-script."""

    async def generate_response(self, context):
        return _OFF_SCRIPT


def _assert_fixed(result, expected: str) -> None:
    assert result["response_text"] == expected
    assert "Con gusto" not in result["response_text"]


async def _node(**kwargs):
    node, repository, gateway = await make_node_and_conversation(
        llm_provider=_ImprovisingLLM(), **kwargs
    )
    return node, repository, gateway


# --- Confirmation proposals --------------------------------------------------


@pytest.mark.asyncio
async def test_the_cancel_proposal_shows_its_fixed_text_when_the_model_improvises():
    slot = future_slot()
    node, _, gateway = await _node(available_slots=[slot])
    appointment = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}{appointment.id}",
            collected_data={
                "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
                "patient": _PATIENT,
                "patient_appointments": [appointment],
                "professional_names": {"prof-1": "Dra. Laura Pérez"},
                "operation": CANCEL_APPOINTMENT_ACTION,
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["response_text"].startswith(
        "Vas a cancelar tu turno con Dra. Laura Pérez.\n\nConfirmás que querés cancelarlo?"
    )
    assert "Con gusto" not in result["response_text"]
    assert result["response_buttons"] == _CONFIRM_BUTTONS


@pytest.mark.asyncio
async def test_the_reschedule_proposal_shows_its_fixed_text_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(available_slots=[slot])

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
            collected_data={
                "stage": STAGE_AWAITING_SLOT_SELECTION,
                "operation": RESCHEDULE_APPOINTMENT_ACTION,
                "rescheduling_appointment_id": "apt-1",
                "patient": _PATIENT,
                "available_slots": [slot],
                "professional_names": {"prof-1": "Dra. Laura Pérez"},
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["response_text"].startswith(
        "Vas a reagendar tu turno con Dra. Laura Pérez.\n\nConfirmás el cambio?"
    )
    assert "Con gusto" not in result["response_text"]
    assert result["response_buttons"] == _CONFIRM_BUTTONS


@pytest.mark.asyncio
async def test_the_create_proposal_shows_its_fixed_text_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(available_slots=[slot])

    result = await identify_and_confirm(
        node,
        "Juan Perez, 30123456",
        {
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "pending_selected_slot": slot,
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["response_text"].startswith(
        "Tengo disponible con Dra. Laura Pérez.\n\nConfirmás que querés reservar este turno?"
    )
    assert "Con gusto" not in result["response_text"]
    assert result["response_buttons"] == _CONFIRM_BUTTONS


# --- Flow sends --------------------------------------------------------------


def _slot_tap_state(slot):
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
async def test_the_verification_flow_intro_is_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(available_slots=[slot], verification_flow_id="flow-verify")

    result = await node(_slot_tap_state(slot))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_FLOW
    assert result["response_flow"].flow_id == "flow-verify"
    _assert_fixed(result, _SEND_VERIFICATION_FLOW_MESSAGE)


@pytest.mark.asyncio
async def test_the_patient_intake_flow_intro_is_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(available_slots=[slot], patient_intake_flow_id="flow-intake")

    result = await node(_slot_tap_state(slot))

    assert result["response_flow"].flow_id == "flow-intake"
    _assert_fixed(result, _SEND_INTAKE_FLOW_MESSAGE)


@pytest.mark.asyncio
async def test_the_registration_flow_intro_is_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(
        available_slots=[slot],
        patients=[],
        verification_flow_id="flow-verify",
        registration_flow_id="flow-register",
    )
    payload = f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Juan Perez", "dni": "30123456"}}'

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=payload,
            collected_data={
                "stage": STAGE_AWAITING_VERIFICATION_FLOW,
                "operation": CREATE_APPOINTMENT_ACTION,
                "pending_selected_slot": slot,
                "professional_names": {"prof-1": "Dra. Laura Pérez"},
            },
        )
    )

    assert result["response_flow"].flow_id == "flow-register"
    _assert_fixed(result, _SEND_REGISTRATION_FLOW_MESSAGE)


# --- Reminders, stale taps and menus ----------------------------------------


@pytest.mark.asyncio
async def test_the_confirmation_reminder_is_fixed_when_the_model_improvises():
    provider = make_proposal_repositories_provider()
    node, _, _ = await _node(proposal_repositories_provider=provider)
    async with provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="pending"))

    result = await node(
        make_agent_state(
            user_message="Cancelame el turno, sí, hacelo",
            pending_action_id="pa-1",
            collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
        )
    )

    _assert_fixed(result, _CONFIRMATION_REMINDER)
    assert result["response_buttons"] == _CONFIRM_BUTTONS


@pytest.mark.asyncio
async def test_the_stale_tap_message_is_fixed_when_the_model_improvises():
    node, _, _ = await _node()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-stale",
            collected_data={"stage": STAGE_AWAITING_NO_AVAILABILITY_CHOICE},
        )
    )

    _assert_fixed(result, _STALE_TAP_MESSAGE)


@pytest.mark.asyncio
async def test_the_operation_menu_text_is_fixed_when_the_model_improvises():
    node, _, _ = await _node()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
            pending_action_id=None,
            collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
        )
    )

    _assert_fixed(result, _MAIN_MENU_RESET_MESSAGE)
    assert result["response_buttons"]


@pytest.mark.asyncio
async def test_the_stale_slot_and_slot_reminder_texts_are_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, _ = await _node(available_slots=[slot])
    data = {
        "stage": STAGE_AWAITING_SLOT_SELECTION,
        "patient": _PATIENT,
        "available_slots": [slot],
        "professional_names": {},
    }

    stale = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}unknown-slot",
            collected_data=data,
        )
    )
    reminder = await node(
        make_agent_state(
            conversation_id="conv-1", user_message="el martes a las 10", collected_data=data
        )
    )

    _assert_fixed(stale, node_module._STALE_SLOT_SELECTION_MESSAGE)
    _assert_fixed(reminder, node_module._SLOT_SELECTION_REMINDER)
    assert stale["response_list"] is not None
    assert reminder["response_list"] is not None


@pytest.mark.asyncio
async def test_the_appointment_selection_texts_are_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, gateway = await _node(available_slots=[slot])
    appointment = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    data = {
        "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
        "patient": _PATIENT,
        "patient_appointments": [appointment],
        "professional_names": {},
        "operation": CANCEL_APPOINTMENT_ACTION,
    }

    stale = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}unknown-appt",
            collected_data=data,
        )
    )
    reminder = await node(
        make_agent_state(conversation_id="conv-1", user_message="el de mañana", collected_data=data)
    )

    _assert_fixed(stale, node_module._STALE_APPOINTMENT_SELECTION_MESSAGE)
    _assert_fixed(reminder, node_module._APPOINTMENT_SELECTION_REMINDER)
    assert len(stale["response_buttons"]) == 1


@pytest.mark.asyncio
async def test_the_appointment_picker_invitation_is_fixed_when_the_model_improvises():
    slot = future_slot()
    node, _, gateway = await _node(available_slots=[slot])
    await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )

    result = await identify_and_confirm(
        node,
        "Juan Perez, 30123456",
        {"stage": STAGE_AWAITING_IDENTIFICATION, "operation": CANCEL_APPOINTMENT_ACTION},
    )

    _assert_fixed(result, node_module._CHOOSE_APPOINTMENT_TO_CANCEL_PROMPT)
    assert result["response_buttons"]


@pytest.mark.asyncio
async def test_the_no_appointments_text_is_fixed_when_the_model_improvises():
    node, _, _ = await _node()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    shown = await node(state)
    result = await confirm_identification(node, shown, conversation_id="conv-1")

    _assert_fixed(result, _NO_APPOINTMENTS_MESSAGE)


# --- Decision subgraph -------------------------------------------------------


async def _graph(*, specialties=None, professionals=None, available_slots=None):
    repository = make_conversation_repository()
    await repository.save(make_conversation(id_="conv-1", mode="agent"))
    return build_appointment_decision_graph(
        appointment_gateway=make_dentalink_gateway(
            available_slots=available_slots if available_slots is not None else [],
            professionals=professionals if professionals is not None else [],
        ),
        specialty_gateway=make_specialty_gateway(
            specialties=specialties if specialties is not None else []
        ),
        conversation_repository=repository,
        llm_provider=_ImprovisingLLM(),
    )


def _state(**overrides):
    base = {
        "conversation_id": "conv-1",
        "user_message": "",
        "button_payload": None,
        "recent_messages": [],
        "contact_memory_summary": None,
        "pending_action_id": None,
        "collected_data": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_the_browse_mode_prompt_is_fixed_when_the_model_improvises():
    graph = await _graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[],
    )
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]

    result = await graph.ainvoke(
        _state(
            button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": options,
            },
        )
    )

    _assert_fixed(result, subgraph._NO_SLOTS_FALLBACK_PROMPT)
    assert result["response_buttons"]


@pytest.mark.asyncio
async def test_the_specialty_retry_text_is_fixed_when_the_model_improvises():
    graph = await _graph()
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]

    result = await graph.ainvoke(
        _state(
            user_message="99",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": options,
            },
        )
    )

    _assert_fixed(result, subgraph._SPECIALTY_NOT_UNDERSTOOD_MESSAGE)
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_the_slot_reminder_and_stale_texts_are_fixed_when_the_model_improvises():
    slot = future_slot()
    graph = await _graph(available_slots=[slot])
    data = {
        "stage": STAGE_AWAITING_SLOT_SELECTION,
        "available_slots": [slot],
        "professional_names": {},
    }

    reminder = await graph.ainvoke(_state(user_message="el martes a las 10", collected_data=data))
    stale = await graph.ainvoke(
        _state(button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}unknown-slot", collected_data=data)
    )

    _assert_fixed(reminder, subgraph._SLOT_SELECTION_REMINDER)
    _assert_fixed(stale, subgraph._STALE_SLOT_SELECTION_MESSAGE)
    assert reminder["response_list"] is not None
    assert stale["response_list"] is not None


@pytest.mark.asyncio
async def test_the_slot_invitation_is_fixed_when_the_model_improvises():
    slot = future_slot()
    graph = await _graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
    )
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]

    result = await graph.ainvoke(
        _state(
            button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": options,
            },
        )
    )

    assert result["response_list"] is not None
    assert "Con gusto" not in result["response_text"]
