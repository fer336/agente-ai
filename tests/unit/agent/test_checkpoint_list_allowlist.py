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
from app.domain.value_objects.list_message import ListMessage, ListRow
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_professional


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
