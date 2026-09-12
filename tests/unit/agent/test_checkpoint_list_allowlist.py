"""Regression test for the LangGraph checkpoint msgpack allowlist.

The agent's paginated interactive lists (`ListMessage`/`ListRow`) are produced
by the specialties and appointment nodes and shipped through `response_list`.
`collected_data` and `response_list` traverse the checkpointer on every
multi-turn flow, so those two domain dataclasses must be declared in
`_CHECKPOINT_MSGPACK_MODULES` — otherwise they degrade to plain dicts on
reload (LangGraph's `_create_msgpack_ext_hook` returns the raw kwargs dict
when a type is not allowlisted) and the patient sees a broken/odd list.

This test pins the exact regression that would otherwise silently corrupt
state: serialize a real `response_list` plus a `collected_data` that carries
row-aware state, reload it with the production allowlist, and assert the
domain types come back intact (not as dicts).
"""

import pytest

from app.agent.graph import _CHECKPOINT_MSGPACK_MODULES
from app.agent.nodes.appointment_selection import decision_entry_node_for_stage
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.value_objects.list_message import ListMessage, ListRow
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_professional, make_slot, make_specialty


def _roundtrip(state):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_MSGPACK_MODULES)
    kind, blob = serde.dumps_typed(state)
    return serde.loads_typed((kind, blob))


def test_list_row_and_list_message_survive_checkpoint_roundtrip():
    rows = [
        ListRow(id="PROFESSIONAL:p1", title="👩‍⚕️ Dra. Laura Pérez"),
        ListRow(id="PROFESSIONAL:p2", title="👨‍⚕️ Dr. Juan Gómez"),
        ListRow(id="LIST_MORE", title="Ver más"),
    ]
    response_list = ListMessage(
        button_label="Elegí un profesional",
        rows=rows,
        section_title="Profesionales",
    )
    state = make_agent_state(
        user_message="",
        collected_data={
            "stage": "awaiting_professional_selection",
            "doctors_page": 0,
            "professional_options": [
                make_professional(id_="p1", full_name="Dra. Laura Pérez"),
                make_professional(id_="p2", full_name="Dr. Juan Gómez"),
            ],
            "chosen_specialty_id": "spec-1",
        },
        response_list=response_list,
    )

    loaded = _roundtrip(state)

    # The list message must revive as its domain type, not collapse to a dict.
    assert isinstance(loaded["response_list"], ListMessage)
    assert all(isinstance(row, ListRow) for row in loaded["response_list"].rows)
    assert loaded["response_list"].rows[0].id == "PROFESSIONAL:p1"
    assert loaded["response_list"].rows[-1].title == "Ver más"

    # The cursor/catalog must stay typed through the same reload.
    loaded_professionals = loaded["collected_data"]["professional_options"]
    assert loaded_professionals[0].full_name == "Dra. Laura Pérez"
    assert loaded["collected_data"]["doctors_page"] == 0
    assert loaded["collected_data"]["stage"] == "awaiting_professional_selection"


@pytest.mark.parametrize(
    "module",
    [
        ("app.domain.value_objects.list_message", "ListRow"),
        ("app.domain.value_objects.list_message", "ListMessage"),
    ],
)
def test_paginated_list_types_are_declared_in_checkpoint_allowlist(module):
    assert module in _CHECKPOINT_MSGPACK_MODULES


# --- Old create-selection checkpoints resume without new persisted state
# (PR 3 of the appointment-decision-subgraph migration) ---------------------
#
# These pin the exact "old-checkpoint compatibility" requirement the
# migration's spec demands: a checkpoint written by (or compatible with) the
# pre-subgraph legacy FSM — just `collected_data["stage"]` plus the existing
# option lists it always carried — must still deserialize cleanly through
# the SAME production allowlist, with no new `AppointmentDecisionState`/
# `DecisionResult` type ever needing registration (those are ephemeral
# TypedDicts of primitives/existing allowlisted types, never stored
# directly), and `decision_entry_node_for_stage(...)` must still map the
# reloaded stage back to the correct internal subgraph entry node.


def test_old_specialty_selection_checkpoint_resumes_without_new_persisted_state():
    state = make_agent_state(
        user_message="",
        collected_data={
            "stage": "awaiting_specialty_selection",
            "specialty_options": [make_specialty(id_="spec-1", name="Ortodoncia")],
            "specialties_page": 0,
        },
    )

    loaded = _roundtrip(state)

    assert loaded["collected_data"]["stage"] == "awaiting_specialty_selection"
    loaded_specialties = loaded["collected_data"]["specialty_options"]
    assert isinstance(loaded_specialties[0], Specialty)
    assert loaded_specialties[0].name == "Ortodoncia"
    assert decision_entry_node_for_stage(loaded["collected_data"]["stage"]) == "choose_specialty"


def test_old_professional_selection_checkpoint_resumes_without_new_persisted_state():
    state = make_agent_state(
        user_message="",
        collected_data={
            "stage": "awaiting_professional_selection",
            "chosen_specialty_id": "spec-1",
            "chosen_specialty_name": "Ortodoncia",
            "professional_options": [make_professional(id_="prof-1", full_name="Dra. Laura Pérez")],
            "doctors_page": 0,
        },
    )

    loaded = _roundtrip(state)

    assert loaded["collected_data"]["stage"] == "awaiting_professional_selection"
    loaded_professionals = loaded["collected_data"]["professional_options"]
    assert isinstance(loaded_professionals[0], Professional)
    assert loaded_professionals[0].full_name == "Dra. Laura Pérez"
    assert (
        decision_entry_node_for_stage(loaded["collected_data"]["stage"]) == "choose_professional"
    )


def test_old_slot_selection_checkpoint_resumes_without_new_persisted_state():
    slot = make_slot(id_="slot-1", professional_id="prof-1")
    state = make_agent_state(
        user_message="",
        collected_data={
            "stage": "awaiting_slot_selection",
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    loaded = _roundtrip(state)

    assert loaded["collected_data"]["stage"] == "awaiting_slot_selection"
    loaded_slots = loaded["collected_data"]["available_slots"]
    assert isinstance(loaded_slots[0], AppointmentSlot)
    assert loaded_slots[0].id == "slot-1"
    assert decision_entry_node_for_stage(loaded["collected_data"]["stage"]) == "choose_slot"


@pytest.mark.parametrize(
    "stage",
    [
        "awaiting_no_availability_choice",
        "awaiting_no_slots_choice",
        "awaiting_identification",
        "awaiting_confirmation",
        None,
    ],
)
def test_non_migrated_stage_checkpoints_never_map_to_a_subgraph_entry_node(stage):
    # Old-checkpoint compatibility cuts both ways: a checkpoint for a stage
    # OUTSIDE the migrated first slice must round-trip fine too, and must
    # never be (mis)routed into the decision subgraph.
    state = make_agent_state(user_message="", collected_data={"stage": stage} if stage else {})

    loaded = _roundtrip(state)

    assert loaded["collected_data"].get("stage") == stage
    assert decision_entry_node_for_stage(loaded["collected_data"].get("stage")) is None
