from app.agent.graph import _route_after_resolve_interaction
from app.agent.nodes.resolve_interaction import THANKS_INTENT


def test_the_thanks_intent_ends_the_run_because_the_router_already_answered():
    assert _route_after_resolve_interaction({"intent": THANKS_INTENT}) == "__end__"  # type: ignore[arg-type]


def test_thanks_errors_still_go_to_handle_error():
    assert _route_after_resolve_interaction({"intent": THANKS_INTENT, "error": "x"}) == (  # type: ignore[arg-type]
        "handle_error"
    )
