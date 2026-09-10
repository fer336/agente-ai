"""Clean reactivation node: deterministic welcome after /bot or lazy timeout.

After a `/bot` reactivation (or the lazy 1h timeout in
`app.application.messages.ingest_message`), the conversation carries
`awaiting_fresh_restart=True`. `LangGraphAgentInvoker.handle()` seeds that
flag into the graph state under `FRESH_RESTART_STATE_KEY`, and the router
(`_route_after_mode_check`) sends the turn straight here — skipping intent
classification entirely — so the first turn renders the canonical welcome
menu deterministically instead of letting the LLM free-form-continue the
old conversation (seen live: "Hola! Cómo estás? Perdón, me parece que no
te entendí bien").

Durable history (messages, ContactMemory, checkpoints) is never deleted —
only this turn's BEHAVIOR is reset: the old workflow cursor (stage,
collected_data) dies with the returned empty mapping, and the response is
the canonical welcome + main-menu list, identical to a first contact.
"""

from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

FRESH_RESTART_STATE_KEY = "fresh_restart"


async def fresh_restart_node(state: AgentState) -> dict[str, object]:
    """Render the canonical welcome + main menu, resetting workflow state."""
    collected_data = state.get("collected_data") or {}
    if not collected_data.get(FRESH_RESTART_STATE_KEY):
        return {}

    return {
        "response_text": WELCOME_TEXT,
        "response_list": WELCOME_LIST,
        "response_flow": None,
        "response_location": None,
        "requires_handoff": False,
        # The old workflow cursor dies: returning fresh collected_data
        # (no stage, no flag) so the invoker overwrites the stale one.
        "collected_data": {},
    }


def create_fresh_restart_node() -> AgentNode:
    """Factory matching the repo's other node factories' DI shape."""
    return fresh_restart_node
