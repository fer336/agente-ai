"""Routing tests for the fresh-restart path (clean reactivation after /bot).

When `collected_data` carries the fresh-restart flag (seeded by
`LangGraphAgentInvoker.handle()` from the conversation's
`awaiting_fresh_restart` column), the graph must route straight to the
`fresh_restart` node — skipping intent classification entirely — so the
first turn after reactivation renders the canonical welcome menu
deterministically.
"""

from app.agent.graph import (
    FRESH_RESTART_NODE,
    RESOLVE_INTERACTION_NODE,
    _route_after_mode_check,
)
from tests.fixtures.agent_state import make_agent_state


def test_fresh_restart_flag_routes_to_the_fresh_restart_node():
    state = make_agent_state(collected_data={"fresh_restart": True})

    assert _route_after_mode_check(state) == FRESH_RESTART_NODE


def test_without_the_flag_routing_is_unchanged():
    state = make_agent_state()

    assert _route_after_mode_check(state) == RESOLVE_INTERACTION_NODE
