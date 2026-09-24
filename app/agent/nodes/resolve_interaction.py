from app.agent.nodes.llm_response import generate_or_fallback
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
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)

_MIN_INTENT_CONFIDENCE = 0.5

#: Set by `appointment.py`'s three success branches (create/reschedule/
#: cancel) instead of fully clearing `collected_data`, and consumed ONLY
#: here, on the very next turn. Exists because the generic classifier's own
#: confidence signal is exactly what misfires right after a booking — seen
#: live: the real LLM read a bare "Gracias" (with the just-confirmed
#: booking still in `recent_messages`) as `intent=appointment`, sending the
#: patient back into specialty selection with nothing chosen. A deterministic
#: post-action window sidesteps that: the LLM still judges the message (never
#: a hardcoded keyword list), but only decides "new request or closing
#: reply", not intent classification from scratch.
POST_ACTION_CLOSE_INTENT = "post_action_close"

#: Every intent `_route_after_resolve_interaction` (graph.py) sends to a real
#: business node EXCEPT "appointment" — that one gets its own, stricter
#: check right below (`_is_genuine_new_request`): a bare `intent=appointment`
#: with nothing else is exactly the shape the live misclassification took
#: (see `POST_ACTION_CLOSE_INTENT`'s own docstring), so it alone is not
#: enough evidence of a genuinely new request during a post-action window.
_ROUTABLE_INTENTS = frozenset({"insurance", "specialties", "handoff", "question", "location"})


def _is_genuine_new_request(result: UnderstandingResult) -> bool:
    """Whether `result` is strong enough evidence of a new request to close
    an open post-action window early (see `POST_ACTION_CLOSE_INTENT`).

    `intent=appointment` needs a carried mention/operation/navigation on top
    of confidence — the live bug was the model reading a bare "Gracias"
    (nothing else) as `appointment` with the just-confirmed booking still in
    `recent_messages`. Every other routable intent stays confidence-only:
    "insurance"/"specialties"/"handoff"/"question"/"location" are distinctive
    enough labels that a closing "Gracias" essentially never lands on one.
    """
    if result.confidence < _MIN_INTENT_CONFIDENCE:
        return False
    if result.intent == "appointment":
        return bool(
            result.operation_mention
            or result.specialty_mention
            or result.professional_mention
            or result.navigation_target
        )
    return result.intent in _ROUTABLE_INTENTS


_POST_ACTION_CLOSE_STATIC_MESSAGES = {
    "create_appointment": "De nada! Ahí quedó anotado tu turno, te esperamos.",
    "reschedule_appointment": "De nada! Ya quedó reagendado, nos vemos pronto.",
    "cancel_appointment": "Listo, quedó cancelado. Cualquier cosa, escribime.",
}
_POST_ACTION_CLOSE_DEFAULT_MESSAGE = "De nada! Cualquier otra cosa, decime."

__all__ = [
    "MENU_ADMIN_PAYLOAD",
    "MENU_APPOINTMENT_PAYLOAD",
    "MENU_INSURANCE_PAYLOAD",
    "MENU_LOCATION_PAYLOAD",
    "MENU_SPECIALTIES_PAYLOAD",
    "POST_ACTION_CLOSE_INTENT",
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

_INFORMATION_INTENTS = frozenset({"insurance", "specialties", "question", "location"})
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


#: `operation_mention`/`navigation_target` are set ONLY from THIS turn's
#: fresh `UnderstandingResult` (`_carried_understanding`, above) — they must
#: never outlive the turn that set them. `specialty_mention`/
#: `professional_mention` are deliberately NOT included here: unlike an
#: operation or a navigation request, a specialty/professional the patient
#: already named may still be legitimately relevant several turns later
#: (mid-flow selection), so they stay out of this task's scope.
_PER_TURN_UNDERSTANDING_KEYS = ("operation_mention", "navigation_target")


def _strip_per_turn_understanding(collected_data: dict[str, object]) -> dict[str, object]:
    """Drops any `operation_mention`/`navigation_target` left over from an
    earlier turn before this turn's routing logic ever looks at them
    (review-bae960a902ead91b, T9 — shared root cause of R3-001/R3-002/R3-003).

    Because LangGraph's `collected_data` channel REPLACES rather than
    merges (see `AgentState.collected_data`'s own docstring), once either key
    lands in a checkpoint it survives forever unless a node explicitly
    forwards a `collected_data` update that omits it. Several return paths
    below forward no `collected_data` update at all (a button tap mid-flow,
    the confirmation reminder, ambiguous low-confidence chatter, ...), so
    without this a stale mention/navigation target could ride along turn
    after turn — e.g. a Cancelar tap with nothing left to confirm reading a
    `create` mention set several turns earlier and starting a create flow
    instead of just dropping the proposal (R3-001); a "volver al menú" typed
    while a live proposal intercepted it (T8) leaving `navigation_target`
    stuck at `"main"` for a LATER, unrelated idle turn (R3-002).

    Returns the SAME object when there is nothing to strip, so callers can
    cheaply tell (via `is`) whether a `collected_data` update must now be
    forwarded to actually commit the strip to state.
    """
    if not any(key in collected_data for key in _PER_TURN_UNDERSTANDING_KEYS):
        return collected_data
    return {
        key: value
        for key, value in collected_data.items()
        if key not in _PER_TURN_UNDERSTANDING_KEYS
    }


def _temporary_result(
    intent: str, collected_data: dict[str, object], carried: dict[str, object] | None = None
) -> dict[str, object]:
    stage = collected_data.get("stage")
    result: dict[str, object] = {
        "intent": intent,
        "active_flow": "appointment",
        "active_node": str(stage) if stage is not None else None,
        "resume_node": str(stage) if stage is not None else None,
        "interruption": "temporary",
    }
    if carried:
        result["collected_data"] = {**collected_data, **carried}
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
        collected_data = _strip_per_turn_understanding(state["collected_data"])
        result = await _resolve(state, collected_data, llm_provider)
        if "collected_data" not in result and collected_data is not state["collected_data"]:
            # Something WAS stripped this turn but the branch below forwarded
            # no `collected_data` update of its own — without this, the
            # strip above would be entirely local (never actually committed
            # to state, since the `collected_data` channel only updates when
            # a node's return value includes the key).
            result = {**result, "collected_data": collected_data}
        return result

    return node


async def _resolve(
    state: AgentState, collected_data: dict[str, object], llm_provider: LLMProvider
) -> dict[str, object]:
    stage = collected_data.get("stage")
    has_active_stage = stage is not None
    post_action_context = collected_data.get("post_action_context")
    payload = state["button_payload"]

    if payload is not None:
        global_intent = _GLOBAL_BUTTON_INTENTS.get(payload)
        if global_intent is not None:
            if global_intent == "handoff":
                return {"intent": "handoff", "interruption": "terminate"}
            if has_active_stage and global_intent in _INFORMATION_INTENTS:
                return _temporary_result(global_intent, collected_data)
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
            return _temporary_result("location", collected_data)
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

    if post_action_context is not None and not _is_genuine_new_request(result):
        text = await generate_or_fallback(
            llm_provider,
            state["conversation_id"],
            POST_ACTION_CLOSE_INTENT,
            {"accion_completada": post_action_context},
            _POST_ACTION_CLOSE_STATIC_MESSAGES.get(
                str(post_action_context), _POST_ACTION_CLOSE_DEFAULT_MESSAGE
            ),
            state["recent_messages"],
            state["contact_memory_summary"],
        )
        return {
            "intent": POST_ACTION_CLOSE_INTENT,
            "response_text": text,
            "response_buttons": None,
            "requires_handoff": False,
            "collected_data": {},
        }

    # A genuine new request always drops the now-consumed window,
    # forwarded explicitly below even on the branches that would
    # otherwise omit `collected_data` entirely (`has_active_stage` is
    # always False whenever `post_action_context` was set, since it is
    # only ever written alongside a full `collected_data` reset).
    forward_stripped_collected_data = post_action_context is not None
    if forward_stripped_collected_data:
        collected_data = {
            key: value for key, value in collected_data.items() if key != "post_action_context"
        }

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

    if not has_active_stage and navigation_target == "main":
        # Idle "volver al menú": same reset as MENU_MAIN_PAYLOAD, which
        # appointment.py applies for a "main" navigation with no stage,
        # whatever intent or confidence the classifier reported. Reads
        # THIS turn's fresh `result.navigation_target` (via the local
        # `navigation_target` above), never `collected_data`'s own —
        # a stale `navigation_target` surviving from an earlier turn
        # (T9, R3-002/R3-003) must never itself trigger this reset.
        return {
            "intent": "appointment",
            "collected_data": {**collected_data, **carried},
        }

    if result.confidence < _MIN_INTENT_CONFIDENCE:
        if has_active_stage:
            # Ambiguous chatter inside a workflow belongs to the current
            # node, and nothing this unreliable classification produced
            # is forwarded — `collected_data` is already stripped of any
            # stale operation_mention/navigation_target (T9, the wrapper
            # in `create_resolve_interaction_node.node` forwards it).
            return {"intent": "appointment"}
        if result.operation_mention is not None:
            # A short, unambiguous "quiero cancelar" can score low
            # OVERALL confidence (little else in the utterance to
            # anchor on) while still cleanly naming an operation — that
            # specific signal must not be discarded just because the
            # rest of the classification was uncertain. Seen live: a
            # fresh "Quiero cancelar" with no active stage fell
            # straight to the generic "no entendí" fallback instead of
            # starting the cancel flow, which `appointment.py`'s own
            # "no stage yet" entry point already knows how to read
            # `collected_data["operation_mention"]` for.
            return {
                "intent": "appointment",
                "collected_data": {**collected_data, **carried},
            }
        return {"intent": "unknown"}

    if result.intent == "handoff":
        if forward_stripped_collected_data:
            return {
                "intent": "handoff",
                "interruption": "terminate",
                "collected_data": collected_data,
            }
        return {"intent": "handoff", "interruption": "terminate"}

    if has_active_stage and result.intent in _INFORMATION_INTENTS:
        return _temporary_result(result.intent, collected_data, carried)

    if has_active_stage:
        if carried:
            return {
                "intent": "appointment",
                "collected_data": {**collected_data, **carried},
            }
        return {"intent": "appointment"}

    if not carried:
        if forward_stripped_collected_data:
            return {"intent": result.intent, "collected_data": collected_data}
        return {"intent": result.intent}
    return {
        "intent": result.intent,
        "collected_data": {**collected_data, **carried},
    }
