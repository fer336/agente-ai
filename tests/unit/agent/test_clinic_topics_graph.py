from app.agent.graph import (
    FAQ_TOPIC_NODE,
    _route_after_business_node,
    _route_after_resolve_interaction,
)


def test_faq_topic_intent_routes_to_the_faq_topic_node():
    assert FAQ_TOPIC_NODE == "faq_topic"
    assert _route_after_resolve_interaction({"intent": "faq_topic"}) == FAQ_TOPIC_NODE  # type: ignore[arg-type]


def test_faq_topic_errors_still_go_to_handle_error():
    assert _route_after_resolve_interaction({"intent": "faq_topic", "error": "boom"}) == (  # type: ignore[arg-type]
        "handle_error"
    )
    assert _route_after_business_node({"error": None}) != "handle_error"  # type: ignore[arg-type]


def test_payment_admin_intent_routes_to_the_payment_admin_node():
    from app.agent.graph import PAYMENT_ADMIN_NODE

    assert PAYMENT_ADMIN_NODE == "payment_admin"
    assert _route_after_resolve_interaction({"intent": "payment_admin"}) == PAYMENT_ADMIN_NODE  # type: ignore[arg-type]
    assert _route_after_resolve_interaction({"intent": "payment_admin", "error": "x"}) == (  # type: ignore[arg-type]
        "handle_error"
    )
