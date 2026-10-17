import pytest

from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS, HANDOFF_OFFER_KEY
from app.agent.nodes.fallback import OUT_OF_SCOPE_MESSAGE
from app.agent.nodes.payment_admin import PAYMENT_ADMIN_STATIC_MESSAGE
from app.agent.nodes.question import create_question_node
from app.domain.repositories.llm_provider import ResponseContext
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state

_THREE_BUTTONS = [
    (OPERATION_CREATE_PAYLOAD, "📅 Agendar una cita"),
    (MENU_ADMIN_PAYLOAD, "💬 Administración"),
    (MENU_MAIN_PAYLOAD, "📋 Menú principal"),
]


class _ExplodingLLM(FakeLLMProvider):
    async def generate_response(self, context: ResponseContext) -> str:
        raise AssertionError("a free question never gets LLM-composed text")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_message", "free_answer"),
    [
        (
            "Me duele una muela, ¿qué tengo?",
            "Por lo que describís, podría tratarse de una caries o una sensibilidad profunda.",
        ),
        (
            "¿Cuánto sale una cirugía de encías?",
            "Los costos de una cirugía de encías pueden variar.",
        ),
        ("¿Qué antibiótico me tomo?", "No puedo recetar medicamentos, consultá a un profesional."),
        ("Contame un chiste", "¿Por qué el dentista fue al banco? Para sacar una muela."),
        ("Son unos inútiles", "Lamento que te sientas así, entiendo tu frustración."),
        ("¿Atienden los sábados?", "Sí, atendemos los sábados a la mañana."),
        ("", ""),
    ],
)
async def test_a_free_question_gets_the_fixed_out_of_scope_text_never_the_models_answer(
    user_message, free_answer
):
    node = create_question_node(_ExplodingLLM())
    state = make_agent_state(
        user_message=user_message,
        collected_data={"stage": None, "pending_answer": free_answer} if free_answer else {},
    )

    result = await node(state)

    assert result["response_text"] == OUT_OF_SCOPE_MESSAGE
    assert free_answer not in result["response_text"] or not free_answer
    assert [(b.id, b.title) for b in result["response_buttons"]] == _THREE_BUTTONS
    assert result["requires_handoff"] is False
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
async def test_question_keeps_the_active_stage_so_an_appointment_can_resume():
    node = create_question_node(_ExplodingLLM())
    state = make_agent_state(
        collected_data={
            "stage": "awaiting_slot_selection",
            "pending_answer": "Sí, atendemos los sábados.",
            "chosen_professional_id": "p1",
        }
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"
    assert "pending_answer" not in result["collected_data"]
    assert HANDOFF_OFFER_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_code_request_answer_never_reaches_the_patient():
    node = create_question_node(_ExplodingLLM())
    state = make_agent_state(
        collected_data={"pending_answer": "def sumar(n):\n    return n\n\nprint(sumar(36))"}
    )

    result = await node(state)

    assert result["response_text"] == OUT_OF_SCOPE_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_message", "free_answer"),
    [
        ("¿Se puede pagar en cuotas?", None),
        ("hola", "Podés pagar en 6 cuotas con tarjeta."),
    ],
)
async def test_payment_questions_keep_the_fixed_administration_redirect(user_message, free_answer):
    node = create_question_node(_ExplodingLLM())
    collected_data = {"stage": None}
    if free_answer:
        collected_data["pending_answer"] = free_answer
    state = make_agent_state(user_message=user_message, collected_data=collected_data)

    result = await node(state)

    assert result["response_text"] == PAYMENT_ADMIN_STATIC_MESSAGE
    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS
    assert result["collected_data"][HANDOFF_OFFER_KEY] is True
