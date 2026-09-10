import pytest

from app.agent.nodes.treatment_catalog import create_treatment_catalog_node
from app.domain.value_objects.treatment_catalog import (
    TREATMENT_CATALOG_ITEMS,
    TREATMENT_CATALOG_TEXT,
)
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_answers_with_the_static_treatment_catalog():
    node = create_treatment_catalog_node()

    result = await node(make_agent_state(user_message="¿Qué tratamientos tienen y cuánto cuestan?"))

    assert result["response_text"] == TREATMENT_CATALOG_TEXT
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_lists_every_confirmed_treatment_without_inventing_a_price():
    node = create_treatment_catalog_node()

    result = await node(make_agent_state())

    for item in TREATMENT_CATALOG_ITEMS:
        assert item in result["response_text"]
    # No numeric price anywhere (real price data doesn't exist yet) — the
    # patient is pointed to administración instead.
    assert not any(char.isdigit() for char in result["response_text"])
    assert "administración" in result["response_text"]


@pytest.mark.asyncio
async def test_never_mutates_collected_data_or_advances_a_booking_stage():
    # This is a pure FAQ answer, never a booking step: it must not touch
    # `SpecialtyGateway`, push booking fields into `collected_data`, or
    # set a stage — contrast `specialties.py`'s node, which does exactly
    # that once a specialty is resolved.
    node = create_treatment_catalog_node()
    state = make_agent_state(collected_data={"stage": "awaiting_identification"})

    result = await node(state)

    assert "collected_data" not in result
