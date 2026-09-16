"""Direct tests for the typed create-selection decision subgraph (PR 2 of
the appointment-decision-subgraph migration).

These tests invoke `app.agent.appointment_decision_subgraph`'s compiled
graph directly — no `create_appointment_node(...)` adapter involved — to
pin the subgraph's own routing, payload handling, and safety behavior
before the adapter wiring (added separately in `appointment.py`) ever
delegates to it.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

import app.agent.appointment_decision_subgraph as appointment_decision_subgraph
from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.nodes.appointment_selection import (
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_NO_SLOTS_CHOICE,
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
async def test_staffed_specialty_lookup_wrapper_returns_none_and_warns_on_error(
    monkeypatch, caplog
):
    gateway = AsyncMock()
    gateway.list_professionals.side_effect = RuntimeError("lookup failed")

    result = await appointment_decision_subgraph._staffed_specialty_ids_safe(gateway)

    assert result is None
    gateway.list_professionals.assert_awaited_once_with()
    assert any("failed or timed out" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_staffed_specialty_lookup_wrapper_times_out_and_completes_cancellation(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_lookup(_gateway):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(appointment_decision_subgraph, "_staffed_specialty_ids", blocking_lookup)
    monkeypatch.setattr(
        appointment_decision_subgraph,
        "_STAFFED_SPECIALTY_TIMEOUT",
        timedelta(milliseconds=1),
    )

    result = await appointment_decision_subgraph._staffed_specialty_ids_safe(object())

    assert result is None
    assert started.is_set()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_create_path_shows_all_specialties_when_staffed_lookup_fails(monkeypatch):
    safe_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(
        appointment_decision_subgraph, "_staffed_specialty_ids_safe", safe_lookup
    )
    specialties = [
        make_specialty(id_="cleaning", name="Ortodoncia"),
        make_specialty(id_="whitening", name="Endodoncia"),
    ]
    graph, _, appointment_gateway = await _make_graph(specialties=specialties, professionals=[])

    result = await graph.ainvoke(
        _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})
    )

    safe_lookup.assert_awaited_once_with(appointment_gateway)
    assert result["collected_data"]["specialty_options"] == specialties
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_create_path_keeps_no_specialties_result_for_successful_empty_staffed_set(
    monkeypatch,
):
    safe_lookup = AsyncMock(return_value=set())
    monkeypatch.setattr(
        appointment_decision_subgraph, "_staffed_specialty_ids_safe", safe_lookup
    )
    graph, _, appointment_gateway = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )

    result = await graph.ainvoke(
        _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})
    )

    safe_lookup.assert_awaited_once_with(appointment_gateway)
    assert result["response_text"] == "[fake-response for intent=no_specialties]"
    assert result.get("response_list") is None


@pytest.mark.asyncio
async def test_visible_specialty_and_professional_prompts_do_not_require_numbers():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )

    specialty_result = await graph.ainvoke(
        _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})
    )
    professional_result = await graph.ainvoke(
        _decision_state(
            button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
            },
        )
    )

    assert "número" not in specialty_result["response_text"].casefold()
    assert "Ortodoncia" in specialty_result["response_list"].rows[0].title
    assert "número" not in professional_result["response_text"].casefold()
    assert professional_result["response_list"] is not None


@pytest.mark.asyncio
async def test_visible_specialty_and_professional_retries_resend_lists_without_numbers():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    graph, _, _ = await _make_graph(llm_provider=_ExplodingLLMProvider())
    specialty_result = await graph.ainvoke(
        _decision_state(
            user_message="invalid",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
            },
        )
    )
    professional_result = await graph.ainvoke(
        _decision_state(
            user_message="invalid",
            collected_data={
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "chosen_specialty_id": "cleaning",
                "professional_options": [make_professional(id_="prof-1")],
            },
        )
    )

    assert "número" not in specialty_result["response_text"].casefold()
    assert "Ortodoncia" in specialty_result["response_list"].rows[0].title
    assert "número" not in professional_result["response_text"].casefold()
    assert professional_result["response_list"] is not None


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
    assert "Ortodoncia" in result["response_list"].rows[0].title


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
    assert result["response_buttons"] is None
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}"
    ]


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
    assert "Dra. Laura Pérez" in result["response_list"].rows[0].title


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

    assert "[fake-response for intent=slot_selection_reminder]" in result["response_text"]
    assert result["response_buttons"] is None
    assert len(result["response_list"].rows) == 1


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

    assert "[fake-response for intent=stale_slot_selection]" in result["response_text"]


# --- Availability outcomes -----------------------------------------------


@pytest.mark.asyncio
async def test_availability_with_slots_renders_as_a_list_with_more_than_three():
    # Regression: slots used to render as reply buttons, capped at 3 by
    # WhatsApp — any 4th+ available slot simply never showed.
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
    assert result["response_buttons"] is None
    assert len(result["response_list"].rows) == 5
    assert result["exit_reason"] == "none"


@pytest.mark.asyncio
async def test_no_availability_with_a_known_specialty_exits_to_legacy_no_slots_choice():
    # This session's own brief: a known specialty must offer "ver otros
    # profesionales" instead of discarding it and sending the patient back
    # to the main menu.
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_NO_SLOTS_CHOICE
    assert result["exit_reason"] == "legacy_no_slots"
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


# --- Internal decision-node observability (PR 3) --------------------------


@pytest.mark.asyncio
async def test_choose_specialty_decision_node_is_attributed_when_offering_specialties():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    state = _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_specialty"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


@pytest.mark.asyncio
async def test_choose_professional_decision_node_is_attributed_on_valid_specialty_selection():
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

    assert result["decision_node"] == "choose_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION


@pytest.mark.asyncio
async def test_search_availability_decision_node_is_attributed():
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

    assert result["decision_node"] == "search_availability"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION


@pytest.mark.asyncio
async def test_choose_slot_decision_node_is_attributed():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_slot"
    assert result["exit_reason"] == "begin_identification"


# --- No-slot/no-availability boundary stays legacy-owned (PR 3) -----------


@pytest.mark.asyncio
async def test_route_entry_rejects_no_availability_choice_stage():
    graph, _, _ = await _make_graph()
    state = _decision_state(collected_data={"stage": "awaiting_no_availability_choice"})

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "not_migrated"


@pytest.mark.asyncio
async def test_route_entry_rejects_no_slots_choice_stage():
    graph, _, _ = await _make_graph()
    state = _decision_state(collected_data={"stage": "awaiting_no_slots_choice"})

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "not_migrated"


@pytest.mark.asyncio
async def test_route_entry_rejects_identification_verification_and_registration_stages():
    graph, _, _ = await _make_graph()
    for stage in (
        "awaiting_identification",
        "awaiting_verification_flow",
        "awaiting_verification_confirmation",
        "awaiting_registration_flow",
        "awaiting_appointment_selection",
        "awaiting_reschedule_professional_choice",
    ):
        result = await graph.ainvoke(_decision_state(collected_data={"stage": stage}))
        assert result["exit_reason"] == "not_migrated", stage


# --- No premature PendingAction or Dentalink writes (PR 3 safety) ---------


def test_subgraph_module_never_imports_sensitive_write_use_cases():
    import app.agent.appointment_decision_subgraph as subgraph_module

    forbidden_symbols = {
        "ProposeAppointmentUseCase",
        "ConfirmPendingActionUseCase",
        "RejectPendingActionUseCase",
        "RevalidateAndCreateAppointmentUseCase",
        "RevalidateAndRescheduleAppointmentUseCase",
        "CancelAppointmentUseCase",
    }

    assert forbidden_symbols.isdisjoint(vars(subgraph_module))
