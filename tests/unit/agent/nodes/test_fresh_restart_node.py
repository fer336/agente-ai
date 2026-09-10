"""Unit tests for the `fresh_restart` node (clean reactivation after /bot).

After a `/bot` reactivation (or the lazy 1h timeout), the agent must start
FRESH: the first turn renders the canonical welcome menu deterministically
instead of letting the LLM free-form-continue the old conversation (seen
live: "Hola! Cómo estás? Perdón, me parece que no te entendí bien"). Durable
history is never deleted — only this turn's BEHAVIOR is reset.
"""

import pytest

from app.agent.nodes.fresh_restart import FRESH_RESTART_STATE_KEY, create_fresh_restart_node
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_LOCATION_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
)
from app.domain.value_objects.welcome_menu import WELCOME_TEXT
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_fresh_restart_flag_renders_welcome_menu_deterministically():
    state = make_agent_state(
        collected_data={FRESH_RESTART_STATE_KEY: True, "stage": "awaiting_identification"}
    )

    result = await create_fresh_restart_node()(state)

    assert result["response_text"] == WELCOME_TEXT
    assert result["response_flow"] is None
    assert result["response_location"] is None
    assert result["requires_handoff"] is False
    # The old workflow cursor dies: the returned collected_data carries
    # neither the old stage nor the fresh-restart flag itself.
    assert result["collected_data"].get("stage") is None
    assert FRESH_RESTART_STATE_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_fresh_restart_renders_a_list_message_with_the_main_menu_rows():
    state = make_agent_state(collected_data={FRESH_RESTART_STATE_KEY: True})

    result = await create_fresh_restart_node()(state)

    response_list = result["response_list"]
    row_ids = [row.id for row in response_list.rows]
    assert row_ids == [
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        MENU_LOCATION_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
        OPERATION_VIEW_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_fresh_restart_flag_absent_runs_nothing():
    state = make_agent_state(collected_data={"stage": "awaiting_identification"})

    result = await create_fresh_restart_node()(state)

    assert result == {}


@pytest.mark.asyncio
async def test_fresh_restart_flag_false_runs_nothing():
    state = make_agent_state(collected_data={FRESH_RESTART_STATE_KEY: False})

    result = await create_fresh_restart_node()(state)

    assert result == {}
