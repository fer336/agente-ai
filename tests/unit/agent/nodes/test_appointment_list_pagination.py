"""Paginated interactive list tests for `appointment.py`'s specialty and
professional selection stages, plus the LIST_MORE/LIST_BACK navigation."""

import pytest

from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_professional, make_specialty
from tests.unit.agent.nodes.test_appointment_node import _make_node_and_conversation


def _specialties(n: int) -> list:
    return [make_specialty(id_=f"spec-{i}", name=f"Especialidad {i}") for i in range(n)]


def _professionals(n: int) -> list:
    return [
        make_professional(id_=f"prof-{i}", full_name=f"Profesional {i}", specialty_id="spec-1")
        for i in range(n)
    ]


def _staffed(n: int) -> list:
    return [
        make_professional(id_=f"prof-{i}", full_name=f"Profesional {i}", specialty_id=f"spec-{i}")
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_specialty_offering_sends_a_paginated_list_message():
    node, _, _ = await _make_node_and_conversation(
        specialties=_specialties(12),
        professionals=_staffed(12),
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload="OPERATION_CREATE",
        collected_data={"operation": CREATE_APPOINTMENT_ACTION},
    )

    result = await node(state)

    message = result["response_list"]
    assert message is not None
    ids = [r.id for r in message.rows]
    assert ids[:9] == [f"{SPECIALTY_PAYLOAD_PREFIX}spec-{i}" for i in range(9)]
    assert ids[-1] == LIST_MORE_PAYLOAD
    assert len(message.rows) == 10
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["specialties_page"] == 0


@pytest.mark.asyncio
async def test_list_more_tap_sends_the_next_page():
    node, _, _ = await _make_node_and_conversation(
        specialties=_specialties(20),
        professionals=_staffed(20),
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=LIST_MORE_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": _specialties(20),
            "specialties_page": 0,
        },
    )

    result = await node(state)

    message = result["response_list"]
    ids = [r.id for r in message.rows]
    assert ids[:9] == [f"{SPECIALTY_PAYLOAD_PREFIX}spec-{i}" for i in range(9, 18)]
    assert ids[-1] == LIST_MORE_PAYLOAD
    assert result["collected_data"]["specialties_page"] == 1


@pytest.mark.asyncio
async def test_final_specialty_page_ends_with_volver_atras():
    node, _, _ = await _make_node_and_conversation(
        specialties=_specialties(20),
        professionals=_staffed(20),
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=LIST_MORE_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": _specialties(20),
            "specialties_page": 1,
        },
    )

    result = await node(state)

    ids = [r.id for r in result["response_list"].rows]
    assert ids == [
        f"{SPECIALTY_PAYLOAD_PREFIX}spec-18",
        f"{SPECIALTY_PAYLOAD_PREFIX}spec-19",
        LIST_BACK_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_single_page_specialty_list_has_no_ver_mas():
    node, _, _ = await _make_node_and_conversation(
        specialties=_specialties(3),
        professionals=[make_professional(id_="prof-1", specialty_id="spec-0")],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload="OPERATION_CREATE",
        collected_data={"operation": CREATE_APPOINTMENT_ACTION},
    )

    result = await node(state)

    ids = [r.id for r in result["response_list"].rows]
    assert LIST_MORE_PAYLOAD not in ids
    assert ids[-1] == LIST_BACK_PAYLOAD


@pytest.mark.asyncio
async def test_list_back_from_specialties_returns_to_the_main_menu():
    node, _, _ = await _make_node_and_conversation(specialties=_specialties(3))
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=LIST_BACK_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": _specialties(3),
        },
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert result["response_list"] is not None
    assert result["response_text"]


@pytest.mark.asyncio
async def test_professional_selection_by_row_id_advances_the_flow():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="spec-1"),
            make_professional(id_="prof-9", full_name="Dr. Otro", specialty_id="spec-2"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload="PROFESSIONAL:prof-1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "spec-1",
            "professional_options": _professionals(2),
        },
    )

    result = await node(state)

    assert result["collected_data"]["chosen_professional_id"] == "prof-1"


@pytest.mark.asyncio
async def test_specialty_row_tap_advances_to_professionals():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}spec-1",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="spec-1", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "spec-1"


@pytest.mark.asyncio
async def test_professional_list_more_tap_sends_the_next_page():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=_professionals(20),
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=LIST_MORE_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "spec-1",
            "chosen_specialty_name": "Ortodoncia",
            "professional_options": _professionals(20),
            "doctors_page": 0,
        },
    )

    result = await node(state)

    message = result["response_list"]
    ids = [r.id for r in message.rows]
    assert ids[:9] == [f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-{i}" for i in range(9, 18)]
    assert ids[-1] == LIST_MORE_PAYLOAD
    assert result["collected_data"]["doctors_page"] == 1
    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION


@pytest.mark.asyncio
async def test_professional_list_back_returns_to_the_specialty_list():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=LIST_BACK_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "spec-1",
            "chosen_specialty_name": "Ortodoncia",
            "professional_options": [make_professional(id_="prof-1", specialty_id="spec-1")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    # Going back to the specialty list invalidates the specialty choice and
    # everything that depends on it, so the operation the patient is in the
    # middle of is the only thing carried over.
    assert "chosen_specialty_id" not in result["collected_data"]
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["response_list"] is not None
