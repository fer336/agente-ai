from app.agent.graph import REMINDER_ACTION_NODE, _route_after_resolve_interaction
from tests.fixtures.agent_state import make_agent_state


def test_reminder_action_intent_routes_to_the_reminder_action_node() -> None:
    state = make_agent_state(intent="reminder_action")

    assert _route_after_resolve_interaction(state) == REMINDER_ACTION_NODE
