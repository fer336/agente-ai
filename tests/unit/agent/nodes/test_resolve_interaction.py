import pytest

from app.agent.nodes.resolve_interaction import (
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
    POST_ACTION_CLOSE_INTENT,
    create_resolve_interaction_node,
)
from app.domain.repositories.llm_provider import UnderstandingResult
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_classifies_appointment_intent():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="Quiero pedir un turno"))

    assert result["intent"] == "appointment"


@pytest.mark.asyncio
async def test_a_plain_question_carries_the_models_own_answer():
    # The whole point of the hybrid: a question the graph has no operation
    # for gets answered in words instead of bouncing back the menu.
    class _AnsweringLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="question",
                confidence=0.95,
                answer="Sí, atendemos los sábados a la mañana.",
            )

    node = create_resolve_interaction_node(_AnsweringLLMProvider())

    result = await node(make_agent_state(user_message="¿atienden los sábados?"))

    assert result["intent"] == "question"
    assert result["collected_data"]["pending_answer"] == "Sí, atendemos los sábados a la mañana."


@pytest.mark.asyncio
async def test_mentions_are_carried_into_collected_data():
    class _MentioningLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="appointment",
                confidence=0.9,
                specialty_mention="ortodoncia",
                operation_mention="create",
            )

    node = create_resolve_interaction_node(_MentioningLLMProvider())

    result = await node(make_agent_state(user_message="quiero un turno de ortodoncia"))

    assert result["collected_data"]["specialty_mention"] == "ortodoncia"
    assert result["collected_data"]["operation_mention"] == "create"


@pytest.mark.asyncio
async def test_a_low_confidence_operation_mention_still_starts_the_flow_with_no_active_stage():
    # Regression, seen live: "Quiero cancelar" with no active stage scored
    # low OVERALL confidence (a short utterance gives the classifier little
    # else to anchor on) and fell straight to the generic "no entendí"
    # fallback instead of starting the cancel flow — even though the
    # classifier correctly named the operation. `appointment.py`'s own
    # "no stage yet" entry point already reads `operation_mention` from
    # `collected_data`; the bug was this node discarding it before it ever
    # got there.
    class _LowConfidenceCancelLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="appointment",
                confidence=0.2,
                operation_mention="cancel",
            )

    node = create_resolve_interaction_node(_LowConfidenceCancelLLMProvider())

    result = await node(make_agent_state(user_message="Quiero cancelar"))

    assert result["intent"] == "appointment"
    assert result["collected_data"]["operation_mention"] == "cancel"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("quiero cancelar mi turno", "cancel"),
        ("quiero reagendar", "reschedule"),
        ("quiero sacar un turno", "create"),
    ],
)
async def test_free_text_operation_requests_reach_the_appointment_flow(
    message: str, operation: str
) -> None:
    # T3(b) of the fallback-menu-buttons change: cancel/reschedule/book have
    # no dedicated buttons — the patient names the operation in plain text
    # and `FakeLLMProvider.understand()`'s real keyword layer (not a stub)
    # must carry it through as `operation_mention`, exactly like a real
    # provider's structured extraction would. `appointment.py`'s "no stage
    # yet" entry point already consumes `operation_mention` from here (see
    # `test_a_stated_cancel_skips_to_identification`/
    # `test_the_welcome_lists_create_row_skips_the_operation_menu` in
    # `test_appointment_node.py`).
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=message))

    assert result["intent"] == "appointment"
    assert result["collected_data"]["operation_mention"] == operation


@pytest.mark.asyncio
async def test_low_confidence_chatter_with_no_operation_mention_still_falls_back():
    # The fix above must not swallow genuinely ambiguous chatter — only a
    # concretely named operation earns the override.
    class _LowConfidenceLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="appointment", confidence=0.1)

    node = create_resolve_interaction_node(_LowConfidenceLLMProvider())

    result = await node(make_agent_state(user_message="mmm no sé"))

    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_a_question_mid_flow_temporarily_interrupts_and_preserves_the_stage():
    class _AnsweringLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="question", confidence=0.95, answer="algo")

    node = create_resolve_interaction_node(_AnsweringLLMProvider())

    result = await node(
        make_agent_state(user_message="una duda", collected_data={"stage": "awaiting_x"})
    )

    assert result["intent"] == "question"
    assert result["interruption"] == "temporary"
    assert result["resume_node"] == "awaiting_x"
    assert result["collected_data"]["stage"] == "awaiting_x"


@pytest.mark.asyncio
async def test_a_thank_you_right_after_a_booking_gets_a_warm_close_not_appointment_intent():
    # Regression for the live bug: right after `appointment.py`'s
    # create/reschedule/cancel success branches leave `post_action_context`
    # (the only key left once `collected_data` is otherwise fully reset), a
    # low-confidence/non-actionable read (a bare "Gracias" always classifies
    # this way against `FakeLLMProvider`'s own keyword heuristics — no
    # appointment/insurance/specialty/handoff keyword present) must close
    # warmly instead of falling through to `intent="unknown"`->fallback,
    # which is what let the patient get bounced back into specialty
    # selection with nothing chosen.
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Gracias",
            collected_data={"post_action_context": "create_appointment"},
        )
    )

    assert result["intent"] == POST_ACTION_CLOSE_INTENT
    assert result["response_text"]
    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_a_confident_but_bare_appointment_misclassification_still_closes_warmly():
    # The exact shape the live bug took: the real LLM read a bare "Gracias"
    # (with the just-confirmed booking still in `recent_messages`) as
    # `intent=appointment` with HIGH confidence and no carried mention/
    # operation/navigation whatsoever. A bare `intent=appointment` alone is
    # not enough evidence of a new request during a post-action window
    # (see `resolve_interaction._is_genuine_new_request`'s own docstring).
    class _OverconfidentLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="appointment", confidence=0.95)

    node = create_resolve_interaction_node(_OverconfidentLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Gracias",
            collected_data={"post_action_context": "create_appointment"},
        )
    )

    assert result["intent"] == POST_ACTION_CLOSE_INTENT
    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_a_genuine_new_request_right_after_a_booking_drops_the_closing_window():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Quiero pedir un turno",
            collected_data={"post_action_context": "create_appointment"},
        )
    )

    assert result["intent"] == "appointment"
    assert "post_action_context" not in result.get("collected_data", {})


@pytest.mark.asyncio
async def test_classifies_insurance_intent():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="¿Trabajan con OSDE?"))

    assert result["intent"] == "insurance"


@pytest.mark.asyncio
async def test_classifies_handoff_intent():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="Necesito hablar con una persona"))

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_classifies_unrecognized_message_as_unknown():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="Hola, buen día"))

    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_treats_low_confidence_classification_as_unknown():
    class _LowConfidenceLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            from app.domain.repositories.llm_provider import IntentResult

            return IntentResult(intent="appointment", confidence=0.1)

    node = create_resolve_interaction_node(_LowConfidenceLLMProvider())

    # No mention of "turno"/"cancelar"/etc: `FakeLLMProvider.understand()`'s
    # own keyword heuristic must not populate `operation_mention` here, or
    # this would exercise the (deliberately separate) low-confidence
    # `operation_mention` carve-out instead of the bare low-confidence path
    # this test targets — see
    # test_low_confidence_chatter_with_no_operation_mention_still_falls_back.
    result = await node(make_agent_state(user_message="mmm, no sé"))

    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_menu_button_payload_routes_deterministically_without_classification():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            raise AssertionError("must not classify when a button payload is present")

    node = create_resolve_interaction_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(user_message="📅 Turnos", button_payload=MENU_APPOINTMENT_PAYLOAD)
    )

    assert result == {"intent": "appointment"}


@pytest.mark.asyncio
async def test_welcome_list_operation_payloads_route_deterministically_to_appointment():
    # The welcome list's booking rows carry `appointment.py`'s own
    # operation payloads directly (this session's own brief) — must
    # route the same as `MENU_APPOINTMENT_PAYLOAD`, no classification.
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            raise AssertionError("must not classify when a button payload is present")

    node = create_resolve_interaction_node(_ExplodingLLMProvider())

    for payload in (OPERATION_CREATE_PAYLOAD, OPERATION_VIEW_PAYLOAD):
        result = await node(
            make_agent_state(user_message="Agendar una cita", button_payload=payload)
        )
        assert result == {"intent": "appointment"}


@pytest.mark.asyncio
async def test_insurance_menu_button_payload_routes_to_insurance():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="🏥 Obras sociales", button_payload=MENU_INSURANCE_PAYLOAD)
    )

    assert result["intent"] == "insurance"


@pytest.mark.asyncio
async def test_specialties_menu_button_payload_routes_to_specialties():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="🦷 Especialidades", button_payload=MENU_SPECIALTIES_PAYLOAD)
    )

    assert result["intent"] == "specialties"


@pytest.mark.asyncio
async def test_classifies_specialties_intent():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="¿Qué especialidades tienen?"))

    assert result["intent"] == "specialties"


@pytest.mark.asyncio
async def test_admin_menu_button_payload_routes_to_handoff():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="💬 Administración", button_payload=MENU_ADMIN_PAYLOAD)
    )

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_admin_menu_button_payload_routes_to_handoff_even_with_an_active_stage():
    # Bug found live: `appointment.py`'s own escape buttons (identification
    # retries, no-slots choice) offer "Administración" mid-flow, but this
    # used to fall into the generic "any button mid-stage -> appointment"
    # rule below and silently reset instead of ever reaching a human.
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            raise AssertionError("must not classify when a button payload is present")

    node = create_resolve_interaction_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(
            user_message="👤 Administración",
            button_payload=MENU_ADMIN_PAYLOAD,
            collected_data={"stage": "awaiting_identification"},
        )
    )

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_unrecognized_button_payload_routes_to_unknown_without_classification():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            raise AssertionError("must not classify when a button payload is present")

    node = create_resolve_interaction_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(user_message="stale button", button_payload="SOME_STALE_PAYLOAD")
    )

    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_active_stage_routes_back_to_appointment_for_ordinary_free_text():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Juan Perez, 12345678",
            collected_data={"stage": "awaiting_identification"},
        )
    )

    assert result == {"intent": "appointment"}


@pytest.mark.asyncio
async def test_stale_operation_mention_is_cleared_when_this_turns_classification_has_none():
    # T5 (review-2358088d31f27658, R3-operation-switch-when-operation-key-
    # absent): `operation_mention` must only ever reflect THIS turn's
    # classification while an appointment stage is active — `specialties.py`'s
    # own `_has_booking_context` docstring already assumes exactly that
    # contract ("the LLM's own understanding of THIS turn's free text").
    # `_carried_understanding` only ever ADDS a fresh mention: without this
    # fix, a mention set on an earlier, unrelated turn (e.g. an aside mid-
    # slot-selection that was never acted on) rides along in
    # `collected_data` forever and later looks like a fresh operation switch
    # at `appointment.py`'s confirmation gate.
    class _NoMentionLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="appointment", confidence=0.9)

    node = create_resolve_interaction_node(_NoMentionLLMProvider())

    result = await node(
        make_agent_state(
            user_message="sí dale",
            collected_data={"stage": "awaiting_confirmation", "operation_mention": "cancel"},
        )
    )

    assert result["intent"] == "appointment"
    assert result["collected_data"].get("operation_mention") is None


@pytest.mark.asyncio
async def test_stale_operation_mention_is_cleared_even_on_low_confidence_active_stage_chatter():
    # Same fix, exercised through the separate low-confidence/active-stage
    # return path, which used to forward no `collected_data` update at all.
    class _LowConfidenceLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="appointment", confidence=0.1)

    node = create_resolve_interaction_node(_LowConfidenceLLMProvider())

    result = await node(
        make_agent_state(
            user_message="mmm",
            collected_data={"stage": "awaiting_confirmation", "operation_mention": "cancel"},
        )
    )

    assert result["intent"] == "appointment"
    assert result["collected_data"].get("operation_mention") is None


@pytest.mark.asyncio
async def test_low_confidence_active_stage_chatter_forwards_no_other_understanding():
    # A classification below the confidence gate is too unreliable to act
    # on: only the stale `operation_mention` is cleared, every other field
    # it produced must stay out of `collected_data`.
    class _LowConfidenceMentioningLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="appointment",
                confidence=0.1,
                specialty_mention="ortodoncia",
                professional_mention="Pérez",
                operation_mention="reschedule",
            )

    node = create_resolve_interaction_node(_LowConfidenceMentioningLLMProvider())
    collected_data = {"stage": "choose_slot", "operation_mention": "cancel"}

    result = await node(make_agent_state(user_message="mmm", collected_data=collected_data))

    assert result["intent"] == "appointment"
    # T9 (review-bae960a902ead91b): the stale `operation_mention` is now
    # dropped entirely at the start of the turn (never even reaches this
    # branch to begin with), rather than explicitly overwritten to `None`.
    assert result["collected_data"] == {"stage": "choose_slot"}


@pytest.mark.asyncio
async def test_idle_navigation_to_main_routes_to_appointment_whatever_the_intent():
    # The real provider can report navigation_target="main" with an
    # "unknown" intent and low confidence. Idle "volver al menú" must still
    # reach appointment.py's MENU_MAIN-equivalent reset.
    class _UnsureNavigatingLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="unknown", confidence=0.2, navigation_target="main")

    node = create_resolve_interaction_node(_UnsureNavigatingLLMProvider())

    result = await node(make_agent_state(user_message="volver al menú", collected_data={}))

    assert result["intent"] == "appointment"
    assert result["collected_data"]["navigation_target"] == "main"


@pytest.mark.asyncio
async def test_active_stage_routes_back_to_appointment_for_a_button_regardless_of_payload():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def classify_intent(self, message, context):
            raise AssertionError("must not classify a button payload, active stage or not")

    node = create_resolve_interaction_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(
            user_message="✅ Confirmar",
            button_payload="CONFIRM_APPOINTMENT",
            collected_data={"stage": "awaiting_confirmation"},
        )
    )

    assert result == {"intent": "appointment"}


@pytest.mark.asyncio
async def test_active_stage_still_escapes_to_handoff_on_the_prd_global_exception_phrases():
    # PRD.md §24.2: "Solicitar administración" remains a valid escape hatch
    # even mid-flow (INTERACTIVE_SELECTION/SENSITIVE_CONFIRMATION), via
    # free text/audio — it just never itself advances the sensitive stage.
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Necesito hablar con una persona",
            collected_data={"stage": "awaiting_confirmation"},
        )
    )

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_menu_main_free_text_reaches_the_same_intent_as_the_button():
    # T3 (free-text menu-intents parity): "volver al menú principal" must
    # reach the same `intent` a real `MENU_MAIN_PAYLOAD` tap does — the
    # actual WELCOME_TEXT/WELCOME_LIST reply parity itself is proven at the
    # `appointment.py` level (`test_navigation_target_main_from_idle_
    # matches_the_menu_main_button` in `test_appointment_node.py`), since
    # this router only ever forwards `navigation_target`, never builds the
    # reply.
    node = create_resolve_interaction_node(FakeLLMProvider())

    button_result = await node(make_agent_state(button_payload=MENU_MAIN_PAYLOAD))
    free_text_result = await node(make_agent_state(user_message="volver al menú principal"))

    assert button_result["intent"] == "appointment"
    assert free_text_result["intent"] == "appointment"
    assert free_text_result["collected_data"]["navigation_target"] == "main"


@pytest.mark.asyncio
async def test_location_free_text_llm_label_reaches_the_same_intent_as_the_button():
    # Unlike "cómo llegar?" (already covered by
    # `test_free_text_location_does_not_get_trapped_by_active_stage` in
    # `test_resolve_interaction_v2.py`, resolved by the deterministic
    # `asks_for_location` substring pre-check before the LLM is ever
    # called), "cómo hago para llegar" deliberately evades that pre-check
    # (extra words in between) — this proves the NEW "location"
    # `understand()` label (T3) carries THIS phrasing to the same place
    # the button goes, through the LLM path instead.
    node = create_resolve_interaction_node(FakeLLMProvider())

    button_result = await node(make_agent_state(button_payload=MENU_LOCATION_PAYLOAD))
    free_text_result = await node(make_agent_state(user_message="cómo hago para llegar"))

    assert button_result["intent"] == "location"
    assert free_text_result["intent"] == "location"


@pytest.mark.asyncio
async def test_handoff_free_text_reaches_the_same_intent_as_the_admin_button():
    # T3: parity test only — handoff free text already worked
    # (`test_active_stage_still_escapes_to_handoff_on_the_prd_global_
    # exception_phrases` above), this just proves it explicitly against
    # the button's own intent instead of independently re-asserting
    # "handoff".
    node = create_resolve_interaction_node(FakeLLMProvider())

    button_result = await node(
        make_agent_state(user_message="💬 Administración", button_payload=MENU_ADMIN_PAYLOAD)
    )
    free_text_result = await node(
        make_agent_state(user_message="necesito hablar con administración")
    )

    assert button_result["intent"] == free_text_result["intent"] == "handoff"
    assert button_result["interruption"] == free_text_result["interruption"] == "terminate"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("button_payload", "message", "operation"),
    [
        (OPERATION_CREATE_PAYLOAD, "quiero sacar un turno", "create"),
        (OPERATION_CANCEL_PAYLOAD, "quiero cancelar mi turno", "cancel"),
        (OPERATION_RESCHEDULE_PAYLOAD, "quiero reagendar", "reschedule"),
        (OPERATION_VIEW_PAYLOAD, "qué turno tengo", "view"),
    ],
)
async def test_operation_free_text_reaches_the_same_intent_as_its_button(
    button_payload: str, message: str, operation: str
) -> None:
    # T3: parity test only — free-text operation requests already reached
    # `appointment.py` (`test_free_text_operation_requests_reach_the_
    # appointment_flow` above); this proves it explicitly against each
    # matching button's own `intent`, one parametrized case per operation.
    node = create_resolve_interaction_node(FakeLLMProvider())

    button_result = await node(make_agent_state(button_payload=button_payload))
    free_text_result = await node(make_agent_state(user_message=message))

    assert button_result["intent"] == "appointment"
    assert free_text_result["intent"] == "appointment"
    assert free_text_result["collected_data"]["operation_mention"] == operation


@pytest.mark.asyncio
async def test_a_stale_operation_mention_does_not_survive_a_button_tap_mid_flow():
    # T9 (review-bae960a902ead91b, R3-001's shared root cause): a button tap
    # never goes through the LLM's `understand()` call at all, so it can
    # never itself set a fresh `operation_mention` — any mention already
    # sitting in `collected_data` at this point can only be a leftover from
    # an earlier, unrelated turn and must not survive into this one (before
    # this fix, this branch forwarded no `collected_data` update at all, so
    # the stale mention rode along unchanged — see R3-001 in
    # `test_appointment_node.py` for the resulting live bug: a Cancelar tap
    # with nothing left to confirm silently starting a create flow).
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            button_payload="CONFIRM_APPOINTMENT",
            collected_data={"stage": "awaiting_confirmation", "operation_mention": "create"},
        )
    )

    assert result == {"intent": "appointment", "collected_data": {"stage": "awaiting_confirmation"}}


@pytest.mark.asyncio
async def test_idle_navigation_reads_this_turns_result_not_a_stale_collected_data_value():
    # T9 (review-bae960a902ead91b, R3-003): pins existing, already-correct
    # behavior — the idle "volver al menú" branch keys off THIS turn's
    # fresh `result.navigation_target`, never `collected_data`'s own
    # (potentially stale) value. A `navigation_target="main"` left over
    # from an earlier turn must not itself force the main-menu intent when
    # this turn's own classification names something else entirely.
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="qué especialidades tienen",
            collected_data={"navigation_target": "main"},
        )
    )

    assert result["intent"] == "specialties"
    assert "navigation_target" not in result.get("collected_data", {"navigation_target": "main"})
