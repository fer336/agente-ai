"""Characterization tests for the pure create-selection helpers extracted
from the legacy appointment node (PR 1 of the appointment-decision-subgraph
migration).

PR 1 is a no-behavior-change extraction: these tests pin the extracted
seam — the legacy-stage-to-decision-node compatibility mapping, payload
resolution, pagination, and slot list/button builders — so the typed
subgraph of PR 2 can build on it without any user-visible drift.
"""

from datetime import UTC, datetime, timedelta

from app.agent.nodes.appointment import (
    SELECT_SLOT_PAYLOAD_PREFIX as _LEGACY_SELECT_SLOT_PREFIX,
)
from app.agent.nodes.appointment import (
    STAGE_AWAITING_NO_AVAILABILITY_CHOICE as _LEGACY_NO_AVAILABILITY_STAGE,
)
from app.agent.nodes.appointment import (
    STAGE_AWAITING_NO_SLOTS_CHOICE as _LEGACY_NO_SLOTS_STAGE,
)
from app.agent.nodes.appointment import (
    STAGE_AWAITING_PROFESSIONAL_SELECTION as _LEGACY_PROFESSIONAL_STAGE,
)
from app.agent.nodes.appointment import (
    STAGE_AWAITING_SLOT_SELECTION as _LEGACY_SLOT_STAGE,
)
from app.agent.nodes.appointment import (
    STAGE_AWAITING_SPECIALTY_SELECTION as _LEGACY_SPECIALTY_STAGE,
)
from app.agent.nodes.appointment_selection import (
    LEGACY_STAGE_TO_DECISION_NODE,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
    STAGE_AWAITING_NO_SLOTS_CHOICE,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    current_page,
    decision_entry_node_for_stage,
    format_slot_option,
    next_page,
    numbered_list,
    resolve_by_name,
    resolve_choice,
    resolve_list_choice,
    resolve_numbered_choice,
    slot_button,
    slot_by_id,
    slot_payload_id,
)
from app.agent.workflow_state import invalidate_from
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import (
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)


def _future_slot(id_: str = "slot-1", professional_id: str = "prof-1") -> AppointmentSlot:
    now = datetime.now(UTC)
    start = now + timedelta(days=1)
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id="cleaning",
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


# --- Legacy stage -> internal decision node compatibility mapping ---


def test_mapping_routes_each_migrated_stage_to_its_decision_entry_node():
    assert LEGACY_STAGE_TO_DECISION_NODE == {
        STAGE_AWAITING_SPECIALTY_SELECTION: "choose_specialty",
        STAGE_AWAITING_PROFESSIONAL_SELECTION: "choose_professional",
        STAGE_AWAITING_SLOT_SELECTION: "choose_slot",
    }


def test_entry_node_lookup_returns_none_for_unmapped_and_unknown_stages():
    assert decision_entry_node_for_stage(STAGE_AWAITING_SPECIALTY_SELECTION) == "choose_specialty"
    assert (
        decision_entry_node_for_stage(STAGE_AWAITING_PROFESSIONAL_SELECTION)
        == "choose_professional"
    )
    assert decision_entry_node_for_stage(STAGE_AWAITING_SLOT_SELECTION) == "choose_slot"
    assert decision_entry_node_for_stage(None) is None
    assert decision_entry_node_for_stage("awaiting_identification") is None


def test_no_availability_and_no_slots_stages_are_not_mapped():
    # The no-availability/no-slot follow-up handlers stay legacy-owned in this
    # slice — the mapping must never claim them.
    assert STAGE_AWAITING_NO_AVAILABILITY_CHOICE not in LEGACY_STAGE_TO_DECISION_NODE
    assert STAGE_AWAITING_NO_SLOTS_CHOICE not in LEGACY_STAGE_TO_DECISION_NODE
    assert decision_entry_node_for_stage(STAGE_AWAITING_NO_AVAILABILITY_CHOICE) is None
    assert decision_entry_node_for_stage(STAGE_AWAITING_NO_SLOTS_CHOICE) is None


def test_legacy_appointment_module_still_exposes_the_selection_stage_constants():
    # Compat contract: existing tests and `specialties.py` keep importing the
    # stage constants from the legacy appointment module.
    assert (
        _LEGACY_SPECIALTY_STAGE
        == STAGE_AWAITING_SPECIALTY_SELECTION
        == "awaiting_specialty_selection"
    )
    assert (
        _LEGACY_PROFESSIONAL_STAGE
        == STAGE_AWAITING_PROFESSIONAL_SELECTION
        == "awaiting_professional_selection"
    )
    assert _LEGACY_SLOT_STAGE == STAGE_AWAITING_SLOT_SELECTION == "awaiting_slot_selection"
    assert (
        _LEGACY_NO_AVAILABILITY_STAGE
        == STAGE_AWAITING_NO_AVAILABILITY_CHOICE
        == "awaiting_no_availability_choice"
    )
    assert _LEGACY_NO_SLOTS_STAGE == STAGE_AWAITING_NO_SLOTS_CHOICE == "awaiting_no_slots_choice"


def test_select_slot_payload_prefix_is_unchanged_in_both_modules():
    assert SELECT_SLOT_PAYLOAD_PREFIX == "SELECT_SLOT:"
    assert _LEGACY_SELECT_SLOT_PREFIX == SELECT_SLOT_PAYLOAD_PREFIX


# --- Payload resolution helpers ---


def test_resolve_list_choice_matches_a_row_payload_deterministically():
    index = resolve_list_choice(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}spec-2",
        user_message="",
        payload_prefix=SPECIALTY_PAYLOAD_PREFIX,
        option_ids=["spec-1", "spec-2", "spec-3"],
        option_names=["Ortodoncia", "Endodoncia", "Implantes"],
    )
    assert index == 1


def test_resolve_list_choice_rejects_a_stale_row_payload():
    # A tap on an older list message (an id outside the current window) must
    # never fall through to free-text guessing.
    index = resolve_list_choice(
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}spec-old",
        user_message="1",
        payload_prefix=SPECIALTY_PAYLOAD_PREFIX,
        option_ids=["spec-1"],
        option_names=["Ortodoncia"],
    )
    assert index is None


def test_resolve_list_choice_falls_back_to_number_matching_on_free_text():
    assert (
        resolve_list_choice(
            button_payload=None,
            user_message="2",
            payload_prefix=PROFESSIONAL_PAYLOAD_PREFIX,
            option_ids=["prof-1", "prof-2"],
            option_names=["Dra. Laura Pérez", "Dr. Otro"],
        )
        == 1
    )


def test_resolve_list_choice_falls_back_to_name_matching_on_free_text():
    assert (
        resolve_list_choice(
            button_payload=None,
            user_message="quiero la Dra. Laura Pérez por favor",
            payload_prefix=PROFESSIONAL_PAYLOAD_PREFIX,
            option_ids=["prof-1", "prof-2"],
            option_names=["Dra. Laura Pérez", "Dr. Otro"],
        )
        == 0
    )


def test_resolve_list_choice_returns_none_on_unmatched_free_text():
    assert (
        resolve_list_choice(
            button_payload=None,
            user_message="nada que ver",
            payload_prefix=SPECIALTY_PAYLOAD_PREFIX,
            option_ids=["spec-1"],
            option_names=["Ortodoncia"],
        )
        is None
    )


def test_resolve_numbered_choice_accepts_in_range_numbers_only():
    assert resolve_numbered_choice("1", 3) == 0
    assert resolve_numbered_choice("opción 2", 3) == 1
    assert resolve_numbered_choice("99", 3) is None
    assert resolve_numbered_choice("asdkjasd", 3) is None


def test_resolve_by_name_and_resolve_choice_keep_number_first_then_name():
    assert resolve_by_name("quiero ortodoncia", ["Ortodoncia", "Endodoncia"]) == 0
    assert resolve_choice("2", ["Ortodoncia", "Endodoncia"]) == 1
    assert resolve_choice("endodoncia", ["Ortodoncia", "Endodoncia"]) == 1


def test_numbered_list_renders_one_based_entries():
    assert numbered_list(["Ortodoncia", "Endodoncia"]) == "1. Ortodoncia\n2. Endodoncia"


def test_slot_payload_id_extracts_the_id_after_the_prefix():
    assert slot_payload_id("SELECT_SLOT:slot-7") == "slot-7"
    assert slot_payload_id("CONFIRM_APPOINTMENT") is None
    assert slot_payload_id(None) is None


def test_slot_by_id_finds_the_current_window_slot():
    mine, other = _future_slot(id_="slot-mine"), _future_slot(id_="slot-other")
    assert slot_by_id([mine, other], "slot-other") is other
    assert slot_by_id([mine, other], "slot-gone") is None


# --- Pagination helpers ---


def test_current_page_defaults_to_zero_and_survives_bad_values():
    assert current_page({}, "specialties_page") == 0
    assert current_page({"specialties_page": None}, "specialties_page") == 0
    assert current_page({"specialties_page": 2}, "specialties_page") == 2


def test_next_page_increments_the_stored_page():
    assert next_page({}, "doctors_page") == 1
    assert next_page({"doctors_page": 1}, "doctors_page") == 2


# --- Slot list/button builders (copy and payload must not drift) ---


def test_format_slot_option_names_the_professional_or_falls_back():
    slot = _future_slot(id_="slot-1", professional_id="prof-1")
    names = {"prof-1": "Dra. Laura Pérez"}

    line = format_slot_option(slot, names)

    assert line.startswith("- Dra. Laura Pérez: ")
    assert slot.time_range.start.strftime("%d/%m %H:%M hs") in line


def test_format_slot_option_falls_back_to_a_generic_professional_name():
    slot = _future_slot(id_="slot-1", professional_id="prof-unknown")

    line = format_slot_option(slot, {})

    assert line.startswith("- Profesional: ")


def test_slot_button_keeps_the_payload_and_title_format():
    slot = _future_slot(id_="slot-42")

    button = slot_button(slot)

    assert isinstance(button, InteractiveButton)
    assert button.id == "SELECT_SLOT:slot-42"
    assert button.title == slot.time_range.start.strftime("%d/%m %H:%M")


# --- Selection dependency invalidation (triangulation) ---


def test_specialty_invalidation_clears_professional_and_slot_data_but_not_patient():
    data = {
        "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
        "operation": "create_appointment",
        "chosen_specialty_id": "spec-1",
        "chosen_specialty_name": "Ortodoncia",
        "professional_options": [],
        "doctors_page": 1,
        "chosen_professional_id": "prof-1",
        "available_slots": [_future_slot()],
        "professional_names": {"prof-1": "Dra. Laura Pérez"},
        "pending_selected_slot": _future_slot(id_="slot-9"),
        "patient": {"id": "pat-1", "full_name": "Juan Perez", "dni": "30123456"},
        "verified_patient_id": "pat-1",
    }

    repaired = invalidate_from(data, "specialty")

    # A changed specialty clears every downstream selection...
    assert "chosen_professional_id" not in repaired
    assert "professional_options" not in repaired
    assert "available_slots" not in repaired
    assert "professional_names" not in repaired
    assert "pending_selected_slot" not in repaired
    assert repaired.get("stage") is None
    # ...while patient identity, verification, and the requested operation
    # are independent data and must survive.
    assert repaired["patient"] == data["patient"]
    assert repaired["verified_patient_id"] == "pat-1"
    assert repaired["operation"] == "create_appointment"


def test_professional_invalidation_clears_slot_data_but_keeps_the_specialty():
    data = {
        "stage": STAGE_AWAITING_SLOT_SELECTION,
        "chosen_specialty_id": "spec-1",
        "chosen_specialty_name": "Ortodoncia",
        "chosen_professional_id": "prof-1",
        "professional_options": [],
        "available_slots": [_future_slot()],
        "professional_names": {"prof-1": "Dra. Laura Pérez"},
        "patient": {"id": "pat-1", "full_name": "Juan Perez", "dni": "30123456"},
    }

    repaired = invalidate_from(data, "professional")

    assert "chosen_professional_id" not in repaired
    assert "available_slots" not in repaired
    assert "pending_selected_slot" not in repaired
    assert repaired.get("stage") is None
    # The specialty the patient already chose is upstream and stays.
    assert repaired["chosen_specialty_id"] == "spec-1"
    assert repaired["chosen_specialty_name"] == "Ortodoncia"
    assert repaired["patient"] == data["patient"]


def test_slot_invalidation_clears_only_the_slot_window():
    data = {
        "stage": STAGE_AWAITING_SLOT_SELECTION,
        "chosen_specialty_id": "spec-1",
        "chosen_professional_id": "prof-1",
        "available_slots": [_future_slot()],
        "pending_selected_slot": _future_slot(id_="slot-9"),
        "patient": {"id": "pat-1", "full_name": "Juan Perez"},
    }

    repaired = invalidate_from(data, "slot")

    assert "available_slots" not in repaired
    assert "pending_selected_slot" not in repaired
    assert repaired.get("stage") is None
    assert repaired["chosen_specialty_id"] == "spec-1"
    assert repaired["chosen_professional_id"] == "prof-1"
    assert repaired["patient"] == data["patient"]