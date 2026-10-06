"""Direct tests for the typed create-selection decision subgraph (PR 2 of
the appointment-decision-subgraph migration).

These tests invoke `app.agent.appointment_decision_subgraph`'s compiled
graph directly — no `create_appointment_node(...)` adapter involved — to
pin the subgraph's own routing, payload handling, and safety behavior
before the adapter wiring (added separately in `appointment.py`) ever
delegates to it.
"""

import asyncio
from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

import app.agent.appointment_decision_subgraph as appointment_decision_subgraph
from app.agent.appointment_decision_subgraph import (
    _AGGREGATE_SEARCH_WINDOW,
    _AGGREGATE_TARGET_SLOTS,
    SPECIALTY_SLOTS_REQUEST_KEY,
    build_appointment_decision_graph,
)
from app.agent.nodes.appointment_selection import (
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.menu_payloads import (
    CHOOSE_PROFESSIONAL_PAYLOAD,
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
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
    clinic_timezone=None,
):
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=conversation_id, mode="agent"))
    appointment_gateway = make_dentalink_gateway(
        available_slots=available_slots if available_slots is not None else [],
        professionals=professionals if professionals is not None else [],
        clinic_timezone=clinic_timezone,
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
    slot = _future_slot()
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
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

    # A valid specialty pick now lists its soonest slots across ALL
    # enabled professionals directly, in the same turn — most patients are
    # new and don't know a professional by name, and doctor names/choice
    # shouldn't appear at this point at all.
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert result["response_buttons"] is None
    assert result["response_list"] is not None


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
async def test_a_hallucinated_specialty_list_falls_back_to_the_static_prompt():
    # User-confirmed regression (screenshot): the LLM fabricated its own
    # bulleted specialty list in free text despite the instruccion telling
    # it not to mention one at all. This is the defensive backstop —
    # discard whatever the LLM said and use the safe static prompt
    # instead, whenever the LLM's own text names one of the real options
    # about to be shown in the List.
    class _HallucinatingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            if context.intent == "choose_specialty":
                return "Elegí entre Ortodoncia, Implantes o Estética dental."
            return await super().generate_response(context)

    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        llm_provider=_HallucinatingLLMProvider(),
    )
    state = _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})

    result = await graph.ainvoke(state)

    assert result["response_text"] == appointment_decision_subgraph._CHOOSE_SPECIALTY_PROMPT
    assert "Ortodoncia" not in result["response_text"]


@pytest.mark.asyncio
async def test_a_professional_name_in_the_slots_prompt_falls_back_to_the_static_prompt():
    # The slots screen never names a professional: whatever the LLM words that repeats a real
    # professional name is discarded for the static prompt (deterministic, name-matching).
    class _HallucinatingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            if context.intent == "choose_slot":
                return "Te paso con Marcos Nahuel Alvarez, que tiene buena disponibilidad."
            return await super().generate_response(context)

    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(
                id_="prof-1", full_name="Marcos Nahuel Alvarez", specialty_id="cleaning"
            )
        ],
        available_slots=[_future_slot()],
        llm_provider=_HallucinatingLLMProvider(),
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["response_text"].startswith(
        appointment_decision_subgraph._CHOOSE_AGGREGATED_SLOT_PROMPT
    )
    assert "Marcos Nahuel Alvarez" not in result["response_text"]


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
async def test_visible_specialty_and_slot_prompts_do_not_require_numbers():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[_future_slot()],
    )

    specialty_result = await graph.ainvoke(
        _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})
    )
    professional_result = await graph.ainvoke(
        _decision_state(
            button_payload=CHOOSE_PROFESSIONAL_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
                "chosen_specialty_id": "cleaning",
                "chosen_specialty_name": "Ortodoncia",
            },
        )
    )

    assert "número" not in specialty_result["response_text"].casefold()
    assert "Ortodoncia" in specialty_result["response_list"].rows[0].title
    assert "número" not in professional_result["response_text"].casefold()
    # A stale "Elegir profesional" tap shows slots, never a professional list.
    assert professional_result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_visible_specialty_and_professional_retries_resend_lists_without_numbers():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    graph, _, _ = await _make_graph(
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[_future_slot()],
        llm_provider=_ExplodingLLMProvider(),
    )
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
    # An in-flight professional-selection checkpoint now resolves to the slots screen.
    assert professional_result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_route_entry_rejects_a_stage_outside_the_first_slice():
    graph, _, _ = await _make_graph()
    state = _decision_state(collected_data={"stage": "awaiting_confirmation"})

    result = await graph.ainvoke(state)

    assert result["exit_reason"] == "not_migrated"


# --- SPECIALTY: payload handling ---------------------------------------


@pytest.mark.asyncio
async def test_valid_specialty_row_tap_advances_directly_to_the_slot_list():
    slot = _future_slot()
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert result["response_buttons"] is None
    # One page of next slots: no "Volver" row.
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
    ]
    # No professional name anywhere in the row title — the patient's own
    # ask: only date, day, time and the clock emoji.
    row_title = result["response_list"].rows[0].title
    assert "Pérez" not in row_title
    assert row_title.startswith("🕐 ")


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
async def test_a_second_invalid_specialty_choice_escalates_to_administracion():
    # Regression: "cuando el agente esté medio desorientado, debe pedir
    # hablar con administración y agregar el botón de administración" —
    # re-showing the same list forever left the patient with no way out.
    graph, _, _ = await _make_graph()
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]
    state = _decision_state(
        user_message="99",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": options,
            "specialty_retry_count": 1,
        },
    )

    result = await graph.ainvoke(state)

    assert result["collected_data"] == {}
    assert result.get("response_list") is None
    assert {b.id for b in result["response_buttons"]} == {MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD}
    admin_button = next(b for b in result["response_buttons"] if b.id == MENU_ADMIN_PAYLOAD)
    assert admin_button.title == "💬 Administración"


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
    # Aggregated screen (no professional chosen): one page, no navigation row.
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
    ]


@pytest.mark.asyncio
async def test_list_back_from_the_aggregated_slot_list_returns_to_specialty_selection():
    # A slot list from a valid specialty pick never showed a professional
    # list (or any intermediate screen) — "Volver atrás" must go straight
    # up to specialty selection.
    slot = _future_slot()
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
    )
    state = _decision_state(
        button_payload=LIST_BACK_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "available_slots": [slot],
            "professional_names": {"prof-1": "Marcos Alvarez"},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_specialty"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert "chosen_specialty_id" not in result["collected_data"]
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_list_back_from_a_specific_professionals_slot_list_returns_to_specialty_selection():
    # A professional's own slot list (an explicit "turno con la doctora X") has no professional
    # list to go back to: "Volver atrás" goes up to the specialty list.
    slot = _future_slot()
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
    )
    state = _decision_state(
        button_payload=LIST_BACK_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
            "available_slots": [slot],
            "professional_names": {"prof-1": "Marcos Alvarez"},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_specialty"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert "chosen_professional_id" not in result["collected_data"]
    assert result["response_list"].section_title == "Especialidades"


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


@pytest.mark.asyncio
async def test_specialty_payload_during_slot_selection_searches_the_new_specialty():
    # Production bug: a patient picks a specialty (e.g. "General"), gets
    # the slot list (`stage` becomes `awaiting_slot_selection`), then taps
    # a DIFFERENT specialty on an OLD specialty-list message
    # (`SPECIALTY:<id>`). `route_entry` used to route by `stage` straight
    # to `choose_slot`, whose `slot_id is None` branch treated the payload
    # as a stale slot pick and just re-sent the old list — changing
    # specialty never worked.
    slot_a = AppointmentSlot(
        id="prof-a-slot",
        professional_id="prof-a",
        specialty_id="cleaning",
        time_range=DateTimeRange(
            datetime.now(UTC) + timedelta(days=1), datetime.now(UTC) + timedelta(days=1, hours=1)
        ),
    )
    slot_b = AppointmentSlot(
        id="prof-b-slot",
        professional_id="prof-b",
        specialty_id="endo",
        time_range=DateTimeRange(
            datetime.now(UTC) + timedelta(days=2), datetime.now(UTC) + timedelta(days=2, hours=1)
        ),
    )
    graph, _, _ = await _make_graph(
        specialties=[
            make_specialty(id_="cleaning", name="Ortodoncia"),
            make_specialty(id_="endo", name="Endodoncia"),
        ],
        professionals=[
            make_professional(id_="prof-a", specialty_id="cleaning"),
            make_professional(id_="prof-b", specialty_id="endo"),
        ],
        available_slots=[slot_a, slot_b],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "available_slots": [slot_a],
            "professional_names": {"prof-a": "Prof A"},
            "slots_page": 0,
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["chosen_specialty_id"] == "endo"
    assert result["collected_data"]["available_slots"] == [slot_b]
    row_ids = [row.id for row in result["response_list"].rows]
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot_b.id}" in row_ids
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot_a.id}" not in row_ids


@pytest.mark.asyncio
async def test_specialty_payload_for_the_same_specialty_re_runs_the_search():
    # The exact production case: re-tapping "General" (the SAME specialty
    # already chosen) on the old list must run a FRESH search, not just
    # re-send whatever `available_slots` is already sitting in
    # `collected_data` from before.
    slot = AppointmentSlot(
        id="prof-a-slot",
        professional_id="prof-a",
        specialty_id="cleaning",
        time_range=DateTimeRange(
            datetime.now(UTC) + timedelta(days=1), datetime.now(UTC) + timedelta(days=1, hours=1)
        ),
    )
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-a", specialty_id="cleaning")],
        available_slots=[slot],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "available_slots": [slot],
            "professional_names": {"prof-a": "Prof A"},
            "slots_page": 0,
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    row_ids = [row.id for row in result["response_list"].rows]
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}" in row_ids


@pytest.mark.asyncio
async def test_unknown_specialty_payload_during_slot_selection_keeps_the_stale_fallback():
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}unknown-specialty",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_slot"
    assert "[fake-response for intent=stale_slot_selection]" in result["response_text"]


class _RaisingSpecialtyGateway:
    """Test double whose `list_specialties()` always raises — simulates a
    failing Dentalink call during `route_entry`'s `SPECIALTY:` reroute
    catalog lookup."""

    async def list_specialties(self):
        raise RuntimeError("dentalink is down")


class _HangingSpecialtyGateway:
    """Test double whose `list_specialties()` never resolves — simulates a
    slow/hung Dentalink call. Paired with a monkeypatched (short) reroute
    timeout so tests using it stay fast."""

    async def list_specialties(self):
        await asyncio.sleep(3600)
        return []  # pragma: no cover - never reached


@pytest.mark.asyncio
async def test_specialty_payload_reroute_falls_back_to_stale_when_catalog_lookup_raises():
    # T7a: before this guard, a failing catalog lookup during the reroute
    # would fail the WHOLE turn, where an unrecognized payload at this
    # stage never made an external call at all before this feature existed.
    slot = _future_slot()
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    graph = build_appointment_decision_graph(
        appointment_gateway=make_dentalink_gateway(available_slots=[slot]),
        specialty_gateway=_RaisingSpecialtyGateway(),
        conversation_repository=conversation_repository,
        llm_provider=FakeLLMProvider(),
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_slot"
    assert "[fake-response for intent=stale_slot_selection]" in result["response_text"]


@pytest.mark.asyncio
async def test_specialty_payload_reroute_falls_back_to_stale_when_catalog_lookup_times_out(
    monkeypatch,
):
    monkeypatch.setattr(
        appointment_decision_subgraph, "_SPECIALTY_REROUTE_TIMEOUT", timedelta(seconds=0.01)
    )
    slot = _future_slot()
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    graph = build_appointment_decision_graph(
        appointment_gateway=make_dentalink_gateway(available_slots=[slot]),
        specialty_gateway=_HangingSpecialtyGateway(),
        conversation_repository=conversation_repository,
        llm_provider=FakeLLMProvider(),
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_slot"
    assert "[fake-response for intent=stale_slot_selection]" in result["response_text"]


@pytest.mark.asyncio
async def test_specialty_payload_during_browse_choice_searches_the_new_specialty():
    # T7b: reroute also applies from the browse-choice stage
    # (`STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE` -> `choose_browse_mode`).
    slot_b = AppointmentSlot(
        id="prof-b-slot",
        professional_id="prof-b",
        specialty_id="endo",
        time_range=DateTimeRange(
            datetime.now(UTC) + timedelta(days=1), datetime.now(UTC) + timedelta(days=1, hours=1)
        ),
    )
    graph, _, _ = await _make_graph(
        specialties=[
            make_specialty(id_="cleaning", name="Ortodoncia"),
            make_specialty(id_="endo", name="Endodoncia"),
        ],
        professionals=[make_professional(id_="prof-b", specialty_id="endo")],
        available_slots=[slot_b],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["chosen_specialty_id"] == "endo"
    row_ids = [row.id for row in result["response_list"].rows]
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot_b.id}" in row_ids


@pytest.mark.asyncio
async def test_specialty_payload_during_professional_selection_searches_the_new_specialty():
    # T7b: reroute also applies from professional selection
    # (`STAGE_AWAITING_PROFESSIONAL_SELECTION` -> `choose_professional`).
    slot_b = AppointmentSlot(
        id="prof-b-slot",
        professional_id="prof-b",
        specialty_id="endo",
        time_range=DateTimeRange(
            datetime.now(UTC) + timedelta(days=1), datetime.now(UTC) + timedelta(days=1, hours=1)
        ),
    )
    graph, _, _ = await _make_graph(
        specialties=[
            make_specialty(id_="cleaning", name="Ortodoncia"),
            make_specialty(id_="endo", name="Endodoncia"),
        ],
        professionals=[make_professional(id_="prof-b", specialty_id="endo")],
        available_slots=[slot_b],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "professional_options": [make_professional(id_="prof-a", specialty_id="cleaning")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["chosen_specialty_id"] == "endo"
    row_ids = [row.id for row in result["response_list"].rows]
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot_b.id}" in row_ids


@pytest.mark.asyncio
async def test_specialty_payload_during_reschedule_slot_selection_does_not_reroute():
    # T7b: a reschedule in flight (`rescheduling_appointment_id` set) must
    # stay legacy-owned even when the payload looks like a specialty pick.
    slot = _future_slot()
    graph, _, _ = await _make_graph(available_slots=[slot])
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}endo",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "available_slots": [slot],
            "professional_names": {},
            "rescheduling_appointment_id": "appt-1",
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_slot"
    assert result["exit_reason"] == "not_migrated"


# --- Availability outcomes -----------------------------------------------


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
async def test_offering_specialties_tells_the_llm_not_to_repeat_the_names():
    # Regression, seen live: the model listed the actual specialty names in
    # its own free-text reply, redundant with the interactive list
    # rendered right below it — an explicit suppression instruction must
    # reach the prompt, mirroring `appointment.py`'s own `_offer_appointments`.
    from app.domain.repositories.llm_provider import ResponseContext
    from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider

    captured: list[ResponseContext] = []

    class _CapturingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            captured.append(context)
            return await super().generate_response(context)

    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        llm_provider=_CapturingLLMProvider(),
    )
    state = _decision_state(collected_data={"operation": _CREATE_APPOINTMENT_ACTION})

    await graph.ainvoke(state)

    choose_specialty_context = next(c for c in captured if c.intent == "choose_specialty")
    assert "instruccion" in choose_specialty_context.collected_data


@pytest.mark.asyncio
async def test_search_availability_any_professional_decision_node_is_attributed_on_pick():
    slot = _future_slot()
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[slot],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION


@pytest.mark.asyncio
async def test_a_valid_specialty_pick_lists_the_soonest_slot_across_professionals():
    now = datetime.now(UTC)
    early = AppointmentSlot(
        id="slot-early",
        professional_id="prof-2",
        specialty_id="cleaning",
        time_range=DateTimeRange(now + timedelta(hours=2), now + timedelta(hours=3)),
    )
    later = AppointmentSlot(
        id="slot-later",
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(now + timedelta(days=1), now + timedelta(days=1, hours=1)),
    )
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Marcos Alvarez", specialty_id="cleaning"),
            make_professional(id_="prof-2", full_name="Laura Gomez", specialty_id="cleaning"),
        ],
        available_slots=[later, early],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["available_slots"] == [early, later]
    row_ids = [row.id for row in result["response_list"].rows]
    assert row_ids[0] == f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-early"
    # Neither professional's name appears in either row title.
    row_titles = " ".join(row.title for row in result["response_list"].rows)
    assert "Alvarez" not in row_titles
    assert "Gomez" not in row_titles


class _FechaScopedGateway:
    """Minimal `AppointmentGateway` double that mimics Dentalink's real
    "from `fecha`" indexing: a slot is only returned when its OWN
    clinic-local calendar date is on or after the LITERAL date implied by
    `date_range.start.date()` — taken verbatim, no tz conversion, exactly
    like `DentalinkAppointmentGateway.search_specialty_availability`
    derives its first `fecha` filter.

    This is what exposes the T5a regression: a UTC-aligned window's naive
    `.date()` can land on the wrong clinic-local day for a late-evening
    clinic slot, so the request never asks Dentalink for the right `fecha`
    — invisible to a plain `date_range.contains(...)` fake like
    `FakeDentalinkGateway`.
    """

    def __init__(self, slots, professionals, clinic_timezone):
        self._slots = slots
        self._professionals = professionals
        self.clinic_timezone = clinic_timezone
        self.calls: list[DateTimeRange] = []

    async def search_specialty_availability(self, specialty_id, date_range, limit):
        del specialty_id
        self.calls.append(date_range)
        first_date = date_range.start.date()
        matches = [
            slot
            for slot in self._slots
            if slot.time_range.start.astimezone(self.clinic_timezone).date() >= first_date
            and date_range.contains(slot.time_range.start)
        ]
        return matches[:limit]

    async def list_professionals(self, specialty_id=None):
        return [
            professional
            for professional in self._professionals
            if specialty_id is None or professional.specialty_id == specialty_id
        ]


@pytest.mark.asyncio
async def test_a_valid_specialty_pick_finds_a_late_clinic_local_slot(monkeypatch):
    # Regression (T5a): T2's calendar-day-aligned aggregated search used
    # UTC (`datetime.now(UTC)`) to build both `now` and the day windows.
    # In a UTC-3 clinic, a slot at 22:00 local falls on the NEXT calendar
    # date in UTC — every UTC-day window then asks Dentalink for the
    # wrong `fecha`, and the slot is never found. The fix aligns `now`/
    # the search window to the clinic's OWN local midnight instead.
    clinic_timezone = ZoneInfo("America/Argentina/Buenos_Aires")
    fixed_moment = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)  # 10:00 clinic-local, same day

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_moment.astimezone(tz) if tz is not None else fixed_moment

    monkeypatch.setattr(appointment_decision_subgraph, "datetime", _FixedDatetime)

    late_slot = AppointmentSlot(
        id="prof-1-202609222200",
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(
            datetime(2026, 9, 22, 22, 0, tzinfo=clinic_timezone),
            datetime(2026, 9, 22, 22, 30, tzinfo=clinic_timezone),
        ),
    )
    gateway = _FechaScopedGateway(
        slots=[late_slot],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        clinic_timezone=clinic_timezone,
    )
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    graph = build_appointment_decision_graph(
        appointment_gateway=gateway,
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
        conversation_repository=conversation_repository,
        llm_provider=FakeLLMProvider(),
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    row_ids = [row.id for row in result["response_list"].rows]
    assert f"{SELECT_SLOT_PAYLOAD_PREFIX}{late_slot.id}" in row_ids


@pytest.mark.asyncio
async def test_offer_any_professional_slots_passes_a_clinic_local_range_and_the_real_target(
    monkeypatch,
):
    # Node-level test for `_offer_any_professional_slots` (T5b): records
    # what `date_range`/`target_slot_count` actually reach the use case,
    # independent of whether any slot is found.
    clinic_timezone = ZoneInfo("America/Argentina/Buenos_Aires")
    captured: list[tuple[DateTimeRange, int]] = []

    class _SpyUseCase:
        def __init__(self, gateway):
            del gateway

        async def execute(self, *, specialty_id, date_range, target_slot_count):
            del specialty_id
            captured.append((date_range, target_slot_count))
            return [], {}

    monkeypatch.setattr(
        appointment_decision_subgraph, "SearchAvailabilityAnyProfessionalUseCase", _SpyUseCase
    )
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        clinic_timezone=clinic_timezone,
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    before = datetime.now(UTC)
    await graph.ainvoke(state)
    after = datetime.now(UTC)

    assert len(captured) == 1
    date_range, target_slot_count = captured[0]
    assert target_slot_count == _AGGREGATE_TARGET_SLOTS == 26
    # Starts at "now", in the CLINIC timezone (not UTC — its utcoffset is
    # the clinic's, distinguishing this from the pre-fix UTC-anchored range).
    assert before <= date_range.start <= after
    assert date_range.start.utcoffset() == clinic_timezone.utcoffset(date_range.start)
    # Ends at clinic-local midnight TODAY (the calendar day `date_range.start`
    # itself falls on, in its own tz) + the search window.
    assert _AGGREGATE_SEARCH_WINDOW == timedelta(days=60)
    expected_today_midnight = datetime.combine(
        date_range.start.date(), time.min, tzinfo=date_range.start.tzinfo
    )
    assert date_range.end == expected_today_midnight + _AGGREGATE_SEARCH_WINDOW


@pytest.mark.asyncio
async def test_a_valid_specialty_pick_with_no_availability_offers_the_fallback_screen():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=[],
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "choose_browse_mode"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE
    # The fallback never offers a professional list: another specialty, the main menu or
    # administration (WhatsApp allows 3 reply buttons).
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (LIST_BACK_PAYLOAD, "Otra especialidad"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
    ]
    assert CHOOSE_PROFESSIONAL_PAYLOAD not in {b.id for b in result["response_buttons"]}
    assert "profesional" not in result["response_text"].casefold().replace("[fake-response", "")


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


# --- Next 10 slots, never a professional list ---------------------------


def _many_future_slots(count: int, professional_id: str = "prof-1") -> list[AppointmentSlot]:
    # Same calendar day, 20-minute spacing: always inside the aggregated search window.
    start = datetime.now(UTC) + timedelta(hours=1)
    return [
        AppointmentSlot(
            id=f"{professional_id}-slot-{index}",
            professional_id=professional_id,
            specialty_id="cleaning",
            time_range=DateTimeRange(
                start + timedelta(minutes=20 * index), start + timedelta(minutes=20 * index + 20)
            ),
        )
        for index in range(count)
    ]


async def _aggregated_result(slot_count: int = 14, llm_provider=None):
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=_many_future_slots(slot_count),
        llm_provider=llm_provider,
    )
    return await graph.ainvoke(
        _decision_state(
            button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
            collected_data={
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
            },
        )
    )


@pytest.mark.asyncio
async def test_the_aggregated_screen_is_one_page_of_ten_slots_with_no_navigation_row():
    result = await _aggregated_result(slot_count=14)

    row_ids = [row.id for row in result["response_list"].rows]
    assert len(row_ids) == 10
    assert all(row_id.startswith(SELECT_SLOT_PAYLOAD_PREFIX) for row_id in row_ids)
    assert LIST_MORE_PAYLOAD not in row_ids
    assert LIST_BACK_PAYLOAD not in row_ids
    assert len(result["collected_data"]["available_slots"]) == 10
    assert result["collected_data"]["slots_page"] == 0


@pytest.mark.asyncio
async def test_the_aggregated_screen_text_tells_how_to_escape_without_naming_a_professional():
    result = await _aggregated_result(slot_count=3)

    assert "menú" in result["response_text"]
    assert "administración" in result["response_text"]
    assert "Prof" not in result["response_text"]


@pytest.mark.asyncio
async def test_a_stale_list_more_tap_on_the_single_page_aggregated_screen_reshows_the_same_slots():
    first = await _aggregated_result(slot_count=14)
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )

    result = await graph.ainvoke(
        _decision_state(button_payload=LIST_MORE_PAYLOAD, collected_data=first["collected_data"])
    )

    row_ids = [row.id for row in result["response_list"].rows]
    assert row_ids == [row.id for row in first["response_list"].rows]


@pytest.mark.asyncio
async def test_a_stale_list_back_tap_on_the_aggregated_screen_goes_to_the_specialty_list():
    first = await _aggregated_result(slot_count=14)
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )

    result = await graph.ainvoke(
        _decision_state(button_payload=LIST_BACK_PAYLOAD, collected_data=first["collected_data"])
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_list"].section_title == "Especialidades"


@pytest.mark.asyncio
async def test_a_requested_specialty_goes_straight_to_its_next_slots():
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=_many_future_slots(12),
    )

    result = await graph.ainvoke(
        _decision_state(
            collected_data={
                "operation": _CREATE_APPOINTMENT_ACTION,
                "chosen_specialty_id": "cleaning",
                "chosen_specialty_name": "Ortodoncia",
                SPECIALTY_SLOTS_REQUEST_KEY: True,
            }
        )
    )

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert SPECIALTY_SLOTS_REQUEST_KEY not in result["collected_data"]
    assert len(result["response_list"].rows) == 10
    assert result["response_list"].section_title == "Horarios disponibles"


# --- No professional list anywhere in the create flow ---------------------


def _slots_graph_kwargs(slots):
    return {
        "specialties": [make_specialty(id_="cleaning", name="Ortodoncia")],
        "professionals": [
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning"),
            make_professional(id_="prof-2", full_name="Dr. Otro", specialty_id="cleaning"),
        ],
        "available_slots": slots,
    }


_BROWSE_DATA = {
    "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
    "operation": _CREATE_APPOINTMENT_ACTION,
    "chosen_specialty_id": "cleaning",
    "chosen_specialty_name": "Ortodoncia",
}


@pytest.mark.asyncio
async def test_a_stale_choose_professional_tap_reruns_the_aggregated_search():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(4)))

    result = await graph.ainvoke(
        _decision_state(button_payload=CHOOSE_PROFESSIONAL_PAYLOAD, collected_data=_BROWSE_DATA)
    )

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert len(result["response_list"].rows) == 4
    assert result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_a_stale_choose_professional_tap_without_slots_shows_the_fallback_again():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs([]))

    result = await graph.ainvoke(
        _decision_state(button_payload=CHOOSE_PROFESSIONAL_PAYLOAD, collected_data=_BROWSE_DATA)
    )

    assert result["decision_node"] == "choose_browse_mode"
    assert result.get("response_list") is None
    assert CHOOSE_PROFESSIONAL_PAYLOAD not in {b.id for b in result["response_buttons"]}


@pytest.mark.asyncio
async def test_a_stale_choose_professional_tap_with_an_unknown_specialty_shows_the_specialties():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(4)))
    data = {k: v for k, v in _BROWSE_DATA.items() if not k.startswith("chosen_")}

    result = await graph.ainvoke(
        _decision_state(button_payload=CHOOSE_PROFESSIONAL_PAYLOAD, collected_data=data)
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_list"].section_title == "Especialidades"


@pytest.mark.asyncio
async def test_the_browse_reminder_keeps_the_three_fallback_buttons():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs([]))

    result = await graph.ainvoke(_decision_state(user_message="no sé", collected_data=_BROWSE_DATA))

    assert {b.id for b in result["response_buttons"]} == {
        LIST_BACK_PAYLOAD,
        MENU_MAIN_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [None, f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1", LIST_MORE_PAYLOAD]
)
async def test_an_in_flight_professional_selection_checkpoint_converts_to_the_slots_screen(payload):
    # Old checkpoints stored `awaiting_professional_selection` with a professional list on
    # screen: whatever arrives next shows the specialty's next slots instead.
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(3)))

    result = await graph.ainvoke(
        _decision_state(
            user_message="la doctora" if payload is None else "",
            button_payload=payload,
            collected_data={
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "operation": _CREATE_APPOINTMENT_ACTION,
                "chosen_specialty_id": "cleaning",
                "chosen_specialty_name": "Ortodoncia",
                "professional_options": [make_professional(id_="prof-1")],
                "doctors_page": 0,
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["response_list"].section_title == "Horarios disponibles"
    assert "professional_options" not in result["collected_data"]
    assert "chosen_professional_id" not in result["collected_data"]


@pytest.mark.asyncio
async def test_list_back_on_an_in_flight_professional_selection_goes_to_the_specialties():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(3)))

    result = await graph.ainvoke(
        _decision_state(
            button_payload=LIST_BACK_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "operation": _CREATE_APPOINTMENT_ACTION,
                "chosen_specialty_id": "cleaning",
                "professional_options": [make_professional(id_="prof-1")],
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_list"].section_title == "Especialidades"


@pytest.mark.asyncio
async def test_an_in_flight_professional_selection_without_a_specialty_shows_the_specialties():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(3)))

    result = await graph.ainvoke(
        _decision_state(
            collected_data={
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "operation": _CREATE_APPOINTMENT_ACTION,
                "professional_options": [make_professional(id_="prof-1")],
            }
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


def _explicit_professional_data(**overrides):
    return {
        "operation": _CREATE_APPOINTMENT_ACTION,
        "chosen_specialty_id": "cleaning",
        "chosen_specialty_name": "Ortodoncia",
        "chosen_professional_id": "prof-1",
        "chosen_professional_name": "Dra. Laura Pérez",
        SPECIALTY_SLOTS_REQUEST_KEY: True,
        **overrides,
    }


@pytest.mark.asyncio
async def test_an_explicit_professional_goes_straight_to_that_professionals_slots():
    mine = _many_future_slots(2, professional_id="prof-1")
    other = _many_future_slots(2, professional_id="prof-2")
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(mine + other))

    result = await graph.ainvoke(_decision_state(collected_data=_explicit_professional_data()))

    assert result["decision_node"] == "search_availability"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert SPECIALTY_SLOTS_REQUEST_KEY not in result["collected_data"]
    assert [r.id for r in result["response_list"].rows[:-1]] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}" for slot in mine
    ]
    assert result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_a_professional_without_slots_offers_the_aggregated_slots_of_the_same_specialty():
    only_other = _many_future_slots(3, professional_id="prof-2")
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(only_other))

    result = await graph.ainvoke(_decision_state(collected_data=_explicit_professional_data()))

    assert result["decision_node"] == "search_availability_any_professional"
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"].get("chosen_professional_id") is None
    assert [r.id for r in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}" for slot in only_other
    ]
    assert "Laura" not in result["response_text"]
    assert "menú" in result["response_text"]


@pytest.mark.asyncio
async def test_a_professional_without_slots_and_a_specialty_without_slots_offers_the_fallback():
    graph, _, _ = await _make_graph(**_slots_graph_kwargs([]))

    result = await graph.ainvoke(_decision_state(collected_data=_explicit_professional_data()))

    assert result["decision_node"] == "choose_browse_mode"
    assert {b.id for b in result["response_buttons"]} == {
        LIST_BACK_PAYLOAD,
        MENU_MAIN_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    }


# --- RESCHEDULE: professionals are never shown either ---------------------


def _reschedule_professional_selection(**overrides):
    return {
        "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
        "operation": "reschedule_appointment",
        "rescheduling_appointment_id": "appt-1",
        "chosen_specialty_id": "cleaning",
        "chosen_specialty_name": "Ortodoncia",
        "professional_options": [make_professional(id_="prof-1")],
        **overrides,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [None, f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1", f"{PROFESSIONAL_PAYLOAD_PREFIX}old"]
)
async def test_a_reschedule_professional_selection_converts_to_the_slots_screen(payload):
    graph, _, _ = await _make_graph(**_slots_graph_kwargs(_many_future_slots(5)))

    result = await graph.ainvoke(
        _decision_state(
            user_message="nada que ver",
            button_payload=payload,
            collected_data=_reschedule_professional_selection(),
        )
    )

    data = result["collected_data"]
    assert result["decision_node"] == "search_availability_any_professional"
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["rescheduling_appointment_id"] == "appt-1"
    assert data["operation"] == "reschedule_appointment"
    assert "professional_options" not in data
    assert "professional_retry_count" not in data
    # One page of slots, no navigation row, no professional rows.
    assert len(result["response_list"].rows) == 5
    assert all(r.id.startswith(SELECT_SLOT_PAYLOAD_PREFIX) for r in result["response_list"].rows)


@pytest.mark.asyncio
async def test_a_reschedule_without_slots_offers_the_fallback_not_other_professionals():
    graph, conversation_repository, _ = await _make_graph(**_slots_graph_kwargs([]))

    result = await graph.ainvoke(
        _decision_state(user_message="1", collected_data=_reschedule_professional_selection())
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE
    assert result["decision_node"] == "choose_browse_mode"
    assert CHOOSE_PROFESSIONAL_PAYLOAD not in {b.id for b in result["response_buttons"]}
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"

@pytest.mark.asyncio
async def test_a_valid_specialty_pick_offers_up_to_26_slots_found_beyond_the_first_week():
    # Endodoncia-like: nothing for ~2 weeks, then plenty. Before searching
    # by specialty over a 60-day window the first slot was out of reach.
    now = datetime.now(UTC)
    slots = [
        AppointmentSlot(
            id=f"prof-1-{i:02d}",
            professional_id="prof-1",
            specialty_id="cleaning",
            time_range=DateTimeRange(
                now + timedelta(days=14, hours=i), now + timedelta(days=14, hours=i, minutes=30)
            ),
        )
        for i in range(30)
    ]
    graph, _, _ = await _make_graph(
        specialties=[make_specialty(id_="cleaning", name="Endodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        available_slots=slots,
    )
    state = _decision_state(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}cleaning",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Endodoncia")],
        },
    )

    result = await graph.ainvoke(state)

    assert result["decision_node"] == "search_availability_any_professional"
    assert [s.id for s in result["collected_data"]["available_slots"]] == [
        s.id for s in slots[:26]
    ]
