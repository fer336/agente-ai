from app.agent.nodes.location import asks_for_location
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider, UnderstandingResult
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_INSURANCE_PAYLOAD,
    MENU_LOCATION_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    MENU_TREATMENT_CATALOG_PAYLOAD,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)

_MIN_INTENT_CONFIDENCE = 0.5

__all__ = [
    "MENU_ADMIN_PAYLOAD",
    "MENU_APPOINTMENT_PAYLOAD",
    "MENU_INSURANCE_PAYLOAD",
    "MENU_LOCATION_PAYLOAD",
    "MENU_SPECIALTIES_PAYLOAD",
    "MENU_TREATMENT_CATALOG_PAYLOAD",
    "create_resolve_interaction_node",
]

# These are truly global navigation/actions. They must win even while an
# appointment stage is active. LIST_MORE/LIST_BACK and row payloads are NOT in
# this table because their meaning depends on the currently rendered screen.
_GLOBAL_BUTTON_INTENTS = {
    MENU_APPOINTMENT_PAYLOAD: "appointment",
    MENU_INSURANCE_PAYLOAD: "insurance",
    MENU_ADMIN_PAYLOAD: "handoff",
    MENU_SPECIALTIES_PAYLOAD: "specialties",
    MENU_TREATMENT_CATALOG_PAYLOAD: "treatment_catalog",
    MENU_LOCATION_PAYLOAD: "location",
    MENU_MAIN_PAYLOAD: "appointment",
    OPERATION_CREATE_PAYLOAD: "appointment",
    OPERATION_RESCHEDULE_PAYLOAD: "appointment",
    OPERATION_CANCEL_PAYLOAD: "appointment",
    OPERATION_VIEW_PAYLOAD: "appointment",
}

_OPERATION_PAYLOADS = frozenset(
    {
        MENU_APPOINTMENT_PAYLOAD,
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
        OPERATION_VIEW_PAYLOAD,
    }
)

_INFORMATION_INTENTS = frozenset(
    {"insurance", "specialties", "treatment_catalog", "question", "location"}
)
_NAVIGATION_TARGETS = frozenset({"specialty", "service", "professional", "slot", "main"})

# Only used when there is no active workflow. During a workflow these are
# context-sensitive and must go back to appointment.py's current-stage handler.
_IDLE_BUTTON_INTENTS = {
    LIST_MORE_PAYLOAD: "specialties",
    LIST_BACK_PAYLOAD: "appointment",
}


def _route_idle_button_payload(payload: str) -> str | None:
    if payload.startswith(SPECIALTY_PAYLOAD_PREFIX):
        return "specialties"
    return _GLOBAL_BUTTON_INTENTS.get(payload) or _IDLE_BUTTON_INTENTS.get(payload)


def _carried_understanding(result: UnderstandingResult) -> dict[str, object]:
    return {
        key: value
        for key, value in (
            ("pending_answer", result.answer),
            ("specialty_mention", result.specialty_mention),
            ("professional_mention", result.professional_mention),
            ("operation_mention", result.operation_mention),
            ("navigation_target", result.navigation_target),
        )
        if value is not None
    }


def _temporary_result(
    intent: str, state: AgentState, carried: dict[str, object] | None = None
) -> dict[str, object]:
    stage = state["collected_data"].get("stage")
    result: dict[str, object] = {
        "intent": intent,
        "active_flow": "appointment",
        "active_node": str(stage) if stage is not None else None,
        "resume_node": str(stage) if stage is not None else None,
        "interruption": "temporary",
    }
    if carried:
        result["collected_data"] = {**state["collected_data"], **carried}
    return result


def create_resolve_interaction_node(llm_provider: LLMProvider) -> AgentNode:
    """Global conversational router in front of the operational workflow.

    An active appointment stage is a cursor, not a prison: strong global
    informational intents may interrupt it temporarily, while stage-specific
    free text/buttons still return to appointment. Explicit navigation requests
    are carried to appointment.py, where dependency-aware invalidation decides
    how far to move back without losing independent data.
    """

    async def node(state: AgentState) -> dict[str, object]:
        collected_data = state["collected_data"]
        stage = collected_data.get("stage")
        has_active_stage = stage is not None
        payload = state["button_payload"]

        if payload is not None:
            global_intent = _GLOBAL_BUTTON_INTENTS.get(payload)
            if global_intent is not None:
                if global_intent == "handoff":
                    return {"intent": "handoff", "interruption": "terminate"}
                if has_active_stage and global_intent in _INFORMATION_INTENTS:
                    return _temporary_result(global_intent, state)
                if has_active_stage and payload in _OPERATION_PAYLOADS:
                    return {
                        "intent": "appointment",
                        "active_flow": "appointment",
                        "active_node": str(stage),
                        "resume_node": None,
                        "interruption": "replace",
                    }
                return {"intent": global_intent}

            if has_active_stage:
                # Context-sensitive list rows, pagination, slot buttons and
                # confirmation buttons belong to the appointment stage that
                # rendered them. Never LLM-classify a machine payload.
                return {"intent": "appointment"}

            intent = _route_idle_button_payload(payload)
            return {"intent": intent if intent is not None else "unknown"}

        # Verified location data is a deterministic global concern. Handle it
        # before the LLM so an active stage cannot trap "dónde quedan?".
        if asks_for_location(state["user_message"]):
            if has_active_stage:
                return _temporary_result("location", state)
            return {"intent": "location"}

        context: dict[str, object] = {
            "recent_messages": state["recent_messages"],
            "contact_memory": state["contact_memory_summary"],
            "active_flow": "appointment" if has_active_stage else state.get("active_flow"),
            "active_stage": stage,
            # Raw workflow data is useful for references such as "ese horario"
            # but the LLM still only extracts language; real IDs remain the
            # graph/repository's responsibility.
            "workflow_data": collected_data,
        }
        result = await llm_provider.understand(state["user_message"], context=context)
        carried = _carried_understanding(result)

        navigation_target = result.navigation_target
        if (
            has_active_stage
            and navigation_target is not None
            and navigation_target in _NAVIGATION_TARGETS
        ):
            return {
                "intent": "appointment",
                "active_flow": "appointment",
                "active_node": str(stage),
                "resume_node": None,
                "interruption": "navigation",
                "collected_data": {**collected_data, **carried},
            }

        if result.confidence < _MIN_INTENT_CONFIDENCE:
            # Ambiguous chatter inside a workflow belongs to the current node;
            # outside a workflow it remains a true fallback.
            return {"intent": "appointment"} if has_active_stage else {"intent": "unknown"}

        if result.intent == "handoff":
            return {"intent": "handoff", "interruption": "terminate"}

        if has_active_stage and result.intent in _INFORMATION_INTENTS:
            return _temporary_result(result.intent, state, carried)

        if has_active_stage:
            if carried:
                return {
                    "intent": "appointment",
                    "collected_data": {**collected_data, **carried},
                }
            return {"intent": "appointment"}

        if not carried:
            return {"intent": result.intent}
        return {
            "intent": result.intent,
            "collected_data": {**collected_data, **carried},
        }

    return node
