"""Direct tests for the typed create-selection decision subgraph (PR 2 of
the appointment-decision-subgraph migration).

These tests invoke `app.agent.appointment_decision_subgraph`'s compiled
graph directly — no `create_appointment_node(...)` adapter involved — to
pin the subgraph's own routing, payload handling, and safety behavior
before the adapter wiring (added separately in `appointment.py`) ever
delegates to it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.nodes.appointment_selection import (
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.menu_payloads import (
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.gateways import (
    make_conversation_repository,
    make_dentalink_gateway,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import make_conversation, make_professional, make_specialty

#: Mirrors `app.agent.nodes.appointment.CREATE_APPOINTMENT_ACTION` — the
#: subgraph never imports from `appointment.py` (same one-way-dependency
#: rule PR 1 established for `appointment_selection.py`).
_CREATE_APPOINTMENT_ACTION = "create_appointment"


def _future_slot(id_: str = "slot-1", professional_id: str = "prof-1") -> AppointmentSlot:
    now = datetime.now(UTC)
    start = now + timedelta(days=1)
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id="cleaning",
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


async def _make_graph(
    *,
    specialties=None,
    professionals=None,
    available_slots=None,
    llm_provider=None,
    conversation_id="conv-1",
):
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=conversation_id, mode="agent"))
    appointment_gateway = make_dentalink_gateway(
        available_slots=available_slots if available_slots is not None else [],
        professionals=professionals if professionals is not None else [],
    )
    graph = build_appointment_decision_graph(
        appointment_gateway=appointment_gateway,
        specialty_gateway=make_specialty_gateway(
            specialties=specialties if specialties is not None else []
        ),
        conversation_repository=conversation_repository,
        llm_provider=llm_provider or FakeLLMProvider(),
    )
    return graph, conversation_repository, appointment_gateway


def _decision_state(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
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


# --- Route entry -------------------------------------------------------


@pytest.mark.asyncio
async def test_route_entry_from_specialty_selection_resolves_the_valid_choice():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    state = _decision_state(
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": _CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"


@pytest.mark.asyncio
async def test_route_entry_from_professional_selection_resolves_the_valid_choice():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": _CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"


@pytest.mark.asyncio
async def test_route_entry_from_slot_selection_resolves_a_valid_slot():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "begin_identification"
    assert result["collected_data"]["pending_selected_slot"] == slot


@pytest.mark.asyncio
async def test_route_entry_from_no_stage_with_create_booking_context_offers_specialties():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    state = _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_route_entry_rejects_a_stage_outside_the_first_slice():
    graph, _, _ = await _make_graph()
    state = _decision_state(collected_data={"stage": "awaiting_confirmation"})

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "not_migrated"


# --- SPECIALTY: payload handling ---------------------------------------


@pytest.mark.asyncio
async def test_valid_specialty_row_tap_advances_to_professional_selection():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"


@pytest.mark.asyncio
async def test_invalid_specialty_choice_reprompts_the_same_list():
    graph, _, _ = await _make_graph()
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]
    state = _decision_state(
        user_message="99",
        collected_data={"stage": STAGE_AWAITING_SPECIALTY_SELECTION, "specialty_options": options},
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["specialty_retry_count"] == 1
    assert "Ortodoncia" in result["response_text"]


@pytest.mark.asyncio
async def test_stale_specialty_row_tap_is_rejected():
    graph, _, _ = await _make_graph()
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}old-id",
        collected_data={"stage": STAGE_AWAITING_SPECIALTY_SELECTION, "specialty_options": options},
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["specialty_retry_count"] == 1


# --- PROFESSIONAL: payload handling -------------------------------------


@pytest.mark.asyncio
async def test_valid_professional_row_tap_advances_to_availability_search():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert [b.id for b in result["response_buttons"]] == [f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}"]


@pytest.mark.asyncio
async def test_invalid_professional_choice_reprompts_the_same_list():
    graph, _, _ = await _make_graph()
    state = _decision_state(
        user_message="nada que ver",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["professional_retry_count"] == 1


@pytest.mark.asyncio
async def test_stale_professional_row_tap_is_rejected():
    graph, _, _ = await _make_graph()
    state = _decision_state(
        button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-old",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["professional_retry_count"] == 1


# --- SELECT_SLOT: payload handling --------------------------------------


@pytest.mark.asyncio
async def test_missing_slot_payload_reminds_with_the_current_options():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        user_message="el martes a las 10",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert "elegí uno de los horarios" in result["response_text"].lower()
    assert len(result["response_buttons"]) == 1


@pytest.mark.asyncio
async def test_stale_slot_payload_is_rejected():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}unknown-slot",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert "ya no está disponible" in result["response_text"]


# --- Availability outcomes -----------------------------------------------


@pytest.mark.asyncio
async def test_availability_with_slots_offers_up_to_three_buttons():
    slots = [_future_slot(id_=f"slot-{i}") for i in range(5)]
    graph, conversation_repository, _ = await _make_graph(available_slots=slots)
    state = _decision_state(
        button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert len(result["response_buttons"]) == 3
    assert result["exit_reason"] == "none"


@pytest.mark.asyncio
async def test_no_availability_exits_to_legacy_ownership():
    graph, conversation_repository, _ = await _make_graph(available_slots=[])
    state = _decision_state(
        button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == "awaiting_no_availability_choice"
    assert result["exit_reason"] == "legacy_no_availability"
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


# --- Pre-identification slot selection safety -----------------------------


@pytest.mark.asyncio
async def test_slot_selected_before_identification_stores_it_without_a_pending_action():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "begin_identification"
    assert result["collected_data"]["pending_selected_slot"] == slot
    # No PendingAction proposal, no Dentalink write: only `pending_action_id`
    # ever present here is whatever was already carried in (None), never a
    # freshly-created one.
    assert result.get("pending_action_id") is None


@pytest.mark.asyncio
async def test_reschedule_marker_exits_as_not_migrated():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
            "rescheduling_appointment_id": "appt-1",
        },
    )

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "not_migrated"
