"""Interactive paginated lists for the specialties node (catalog path and
per-specialty professional listing), plus resolve_interaction routing of
the list row payloads."""

import pytest

from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_professional, make_specialty
from tests.unit.agent.nodes.test_specialties_node import _node


@pytest.mark.asyncio
async def test_catalog_path_sends_an_interactive_specialty_list():
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )

    result = await node(
        make_agent_state(user_message="que especialidades tienen?", collected_data={})
    )

    message = result["response_list"]
    assert message is not None
    assert message.rows[0].id == f"{SPECIALTY_PAYLOAD_PREFIX}spec-1"
    assert message.rows[0].title.startswith("🦷 ")


@pytest.mark.asyncio
async def test_specialty_catalog_paginates_with_ver_mas():
    specialties = [make_specialty(id_=f"spec-{i}", name=f"EsPECIALIDAD {i}") for i in range(12)]
    professionals = [
        make_professional(id_=f"prof-{i}", specialty_id=f"spec-{i}") for i in range(12)
    ]
    node = _node(specialties=specialties, professionals=professionals)

    result = await node(make_agent_state(user_message="especialidades", collected_data={}))

    ids = [r.id for r in result["response_list"].rows]
    assert len(ids) == 10
    assert ids[-1] == LIST_MORE_PAYLOAD
    assert result["collected_data"]["specialties_page"] == 0


@pytest.mark.asyncio
async def test_list_more_on_the_catalog_sends_the_next_page():
    specialties = [make_specialty(id_=f"spec-{i}", name=f"Especialidad {i}") for i in range(12)]
    professionals = [
        make_professional(id_=f"prof-{i}", specialty_id=f"spec-{i}") for i in range(12)
    ]
    node = _node(specialties=specialties, professionals=professionals)

    result = await node(
        make_agent_state(
            user_message="",
            button_payload=LIST_MORE_PAYLOAD,
            collected_data={"specialties_page": 0},
        )
    )

    ids = [r.id for r in result["response_list"].rows]
    assert f"{SPECIALTY_PAYLOAD_PREFIX}spec-9" in ids
    assert f"{SPECIALTY_PAYLOAD_PREFIX}spec-8" not in ids
    assert result["collected_data"]["specialties_page"] == 1


@pytest.mark.asyncio
async def test_list_back_on_the_catalog_returns_to_the_main_menu():
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )

    result = await node(
        make_agent_state(
            user_message="",
            button_payload=LIST_BACK_PAYLOAD,
            collected_data={},
        )
    )

    assert result["response_list"] is not None
    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_specialty_row_tap_from_the_catalog_opens_its_professionals():
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="spec-1")],
    )

    result = await node(
        make_agent_state(
            user_message="",
            button_payload=f"{SPECIALTY_PAYLOAD_PREFIX}spec-1",
            collected_data={},
        )
    )

    assert result["collected_data"]["stage"] == "awaiting_professional_selection"
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_professional_listing_from_the_catalog_is_a_paginated_list():
    professionals = [
        make_professional(id_=f"prof-{i}", full_name=f"Profesional {i}", specialty_id="spec-1")
        for i in range(12)
    ]
    node = _node(
        specialties=[make_specialty(id_="spec-1", name="Ortodoncia")],
        professionals=professionals,
    )

    result = await node(make_agent_state(user_message="ortodoncia", collected_data={}))

    ids = [r.id for r in result["response_list"].rows]
    assert ids[-1] == LIST_MORE_PAYLOAD
    assert result["collected_data"]["stage"] == "awaiting_professional_selection"


def _resolver(button_payload):
    return create_resolve_interaction_node(FakeLLMProvider())


class TestResolveInteractionRouting:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (f"{SPECIALTY_PAYLOAD_PREFIX}spec-1", "specialties"),
            (LIST_MORE_PAYLOAD, "specialties"),
            (LIST_BACK_PAYLOAD, "appointment"),
            ("PROFESSIONAL:prof-1", "unknown"),
        ],
    )
    async def test_list_payloads_route_without_an_active_stage(self, payload, expected):
        node = _resolver(payload)
        state = make_agent_state(user_message="", button_payload=payload, collected_data={})
        result = await node(state)
        assert result["intent"] == expected
