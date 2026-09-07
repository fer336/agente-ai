import pytest

from app.agent.nodes.resolve_interaction import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_INSURANCE_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
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
async def test_a_question_mid_flow_never_derails_an_active_stage():
    # A stage in progress still wins: only the handoff escape hatch may
    # interrupt it (PRD.md §24.2), otherwise a stray question would drop
    # the patient's half-finished booking.
    class _AnsweringLLMProvider(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(intent="question", confidence=0.95, answer="algo")

    node = create_resolve_interaction_node(_AnsweringLLMProvider())

    result = await node(
        make_agent_state(user_message="una duda", collected_data={"stage": "awaiting_x"})
    )

    assert result["intent"] == "appointment"


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

    result = await node(make_agent_state(user_message="turno tal vez"))

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
