from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_INSURANCE_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
)

#: Minimum classifier confidence to act on it — below this, PRD.md §8's
#: "Si no puede determinarlo con suficiente seguridad" applies and the
#: turn routes to `fallback` instead.
_MIN_INTENT_CONFIDENCE = 0.5

#: PRD.md §7's welcome-menu button payloads — now sent for real by
#: `IngestMessageUseCase` on a conversation's first turn (see that module's
#: `_WELCOME_BUTTONS`). Re-exported here (defined in
#: `app.domain.value_objects.menu_payloads`, see that module's own
#: docstring for why) so every existing importer of these names from this
#: module keeps working unchanged. Deterministic mapping, never
#: LLM-classified, per PRD.md §6.
__all__ = [
    "MENU_ADMIN_PAYLOAD",
    "MENU_APPOINTMENT_PAYLOAD",
    "MENU_INSURANCE_PAYLOAD",
    "MENU_SPECIALTIES_PAYLOAD",
    "create_resolve_interaction_node",
]

_MENU_BUTTON_INTENTS = {
    MENU_APPOINTMENT_PAYLOAD: "appointment",
    MENU_INSURANCE_PAYLOAD: "insurance",
    MENU_ADMIN_PAYLOAD: "handoff",
    MENU_SPECIALTIES_PAYLOAD: "specialties",
}


def create_resolve_interaction_node(
    llm_provider: LLMProvider,
) -> AgentNode:
    """Routes a turn to appointment/insurance/specialties/handoff/unknown (PRD.md §6, §8).

    - A button payload ALWAYS carries a known intent (PRD.md §6: "Botón ->
      Intención conocida -> LangGraph") and is never reclassified. Mid-flow
      (`collected_data["stage"]` set), any button routes straight back to
      `appointment` — the node itself interprets the payload in the
      context of its own stage. Otherwise, a recognized welcome-menu
      payload maps directly to its intent; an unrecognized one (stale
      button, payload from a flow that no longer applies) routes to
      `unknown` rather than guessing.
    - Free text/audio is always classified via `LLMProvider.classify_intent`
      — even mid-flow, ONLY to honor PRD.md §24.2's global escape hatches
      ("solicitar administración", "no entiendo", urgencia): a `handoff`
      classification wins and interrupts the active stage; anything else
      mid-flow still routes back to `appointment` regardless of what was
      said, since free text/audio must never itself advance
      `INTERACTIVE_SELECTION`/`SENSITIVE_CONFIRMATION` (PRD.md §24.2's
      table) — only a stage-appropriate button does.
    """

    async def node(state: AgentState) -> dict[str, object]:
        has_active_stage = state["collected_data"].get("stage") is not None

        if state["button_payload"] is not None:
            if has_active_stage:
                return {"intent": "appointment"}
            intent = _MENU_BUTTON_INTENTS.get(state["button_payload"])
            return {"intent": intent if intent is not None else "unknown"}

        result = await llm_provider.classify_intent(state["user_message"], context={})

        if has_active_stage:
            if result.intent == "handoff" and result.confidence >= _MIN_INTENT_CONFIDENCE:
                return {"intent": "handoff"}
            return {"intent": "appointment"}

        if result.confidence < _MIN_INTENT_CONFIDENCE:
            return {"intent": "unknown"}
        return {"intent": result.intent}

    return node
