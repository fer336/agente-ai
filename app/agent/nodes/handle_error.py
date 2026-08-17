import logging

from app.agent.state import AgentState

logger = logging.getLogger(__name__)

#: Never leaks the technical error to the patient (PRD.md §55's redaction
#: principle applies in spirit here too) — just a safe, generic fallback
#: that offers a human.
_ERROR_FALLBACK_MESSAGE = (
    "Tuvimos un problema técnico procesando tu mensaje. "
    "¿Querés que te comunique con administración para ayudarte directamente?"
)


async def handle_error_node(state: AgentState) -> dict[str, object]:
    """Safe fallback when a node's `with_error_handling` wrapper caught an exception (PRD.md §30).

    Minimal by design for this change — no `agent_runs`/`node_executions`/
    `errors` persistence yet (that is a separate, later change); this only
    guarantees the conversation gets a safe reply instead of silently
    hanging. Clears `error` back to `None` so it does not leak into the
    NEXT turn's checkpointed state (this node's return is the last thing
    written to the thread's checkpoint for this run).
    """
    logger.warning(
        "agent.handled_error failed_node=%s conversation=%s",
        state.get("error"),
        state["conversation_id"],
    )
    return {"response_text": _ERROR_FALLBACK_MESSAGE, "requires_handoff": False, "error": None}
