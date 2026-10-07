from langgraph.graph import END

from app.agent.graph import (
    APPOINTMENT_NODE,
    HANDLE_ERROR_NODE,
    REMINDER_ACTION_NODE,
    _route_after_reminder_action,
    _route_after_resolve_interaction,
)
from tests.fixtures.agent_state import make_agent_state


def test_reminder_action_intent_routes_to_the_reminder_action_node() -> None:
    state = make_agent_state(intent="reminder_action")

    assert _route_after_resolve_interaction(state) == REMINDER_ACTION_NODE


def test_a_reminder_action_that_hands_over_a_reschedule_continues_in_the_appointment_node() -> None:
    state = make_agent_state(intent="appointment")

    assert _route_after_reminder_action(state) == APPOINTMENT_NODE


def test_every_other_reminder_action_outcome_ends_the_turn_or_handles_the_error() -> None:
    assert _route_after_reminder_action(make_agent_state(intent="reminder_action")) == END
    assert _route_after_reminder_action(make_agent_state(error="boom")) == HANDLE_ERROR_NODE
