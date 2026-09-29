import pytest

from app.agent.nodes.question import create_question_node
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_question_delivers_answer_without_destroying_active_stage():
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(
        collected_data={
            "stage": "awaiting_slot_selection",
            "pending_answer": "Sí, atendemos los sábados.",
            "chosen_professional_id": "p1",
        }
    )

    result = await node(state)

    assert result["response_text"] == "Sí, atendemos los sábados."
    assert result["response_buttons"] is None
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
async def test_question_discards_a_pending_answer_that_looks_like_code():
    # Regression, confirmed live (screenshot): a prompt-injection attempt
    # asking for a recursive Python function talked `understand()`'s
    # "answer" field into acting as a general-purpose coding assistant.
    # This deterministic backstop must never relay that verbatim, no
    # matter what the LLM produced.
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(
        collected_data={
            "stage": None,
            "pending_answer": "def sumar(n):\n    if n == 1:\n        return 1\n"
            "    return n + sumar(n - 1)\n\nprint(sumar(36))",
        }
    )

    result = await node(state)

    assert result["response_text"] == (
        "Solo puedo ayudarte con turnos, especialidades, obra social y datos de la clínica. "
        "Si necesitás otra cosa, te comunico con administración."
    )
    assert "def " not in result["response_text"]
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
async def test_question_fails_closed_through_the_llm_when_no_answer_is_available():
    # Regression: an absent `pending_answer` used to return a hardcoded
    # string directly — now it's LLM-worded too (with a static fallback
    # for when the LLM call itself fails), same "no hardcoded default"
    # direction as every other node in this session.
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(collected_data={"stage": None})

    result = await node(state)

    assert result["response_text"] == "[fake-response for intent=question_unknown_answer]"
    assert result["response_buttons"] is None


_STARTED = [
    {"role": "user", "content": "Hola"},
    {"role": "assistant", "content": "Hola! Soy el asistente de Smiling Pilar."},
    {"role": "user", "content": "¿atienden particulares?"},
]


@pytest.mark.asyncio
async def test_question_answer_never_greets_mid_conversation():
    # Chat A regression (live): "Para un tratamiento particular" got
    # "¡Hola! Sí, atendemos pacientes particulares. Si querés, puedo pasarte con
    # administración…" in the middle of a conversation.
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(
        recent_messages=_STARTED,
        collected_data={"pending_answer": "¡Hola! Sí, atendemos pacientes particulares."},
    )

    result = await node(state)

    assert result["response_text"] == "Sí, atendemos pacientes particulares."


@pytest.mark.asyncio
async def test_question_answer_may_greet_on_the_first_turn():
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(
        recent_messages=[{"role": "user", "content": "Hola, ¿atienden particulares?"}],
        collected_data={"pending_answer": "¡Hola! Sí, atendemos pacientes particulares."},
    )

    result = await node(state)

    assert result["response_text"] == "¡Hola! Sí, atendemos pacientes particulares."


_PARTICULARES_ANSWER = (
    "Sí, atendemos pacientes particulares. Si querés, puedo pasarte con administración "
    "para que te confirmen los valores. ¿Te parece bien?"
)


@pytest.mark.asyncio
async def test_an_answer_that_offers_administration_carries_the_two_handoff_buttons():
    from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD

    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(collected_data={"pending_answer": _PARTICULARES_ANSWER})

    result = await node(state)

    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
    ]
    assert result["collected_data"]["handoff_offer_pending"] is True


@pytest.mark.asyncio
async def test_an_answer_without_a_handoff_offer_has_no_buttons():
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(collected_data={"pending_answer": "Atendemos de lunes a viernes."})

    result = await node(state)

    assert result["response_buttons"] is None
    assert "handoff_offer_pending" not in result["collected_data"]


@pytest.mark.asyncio
async def test_the_unknown_answer_offering_administration_carries_the_handoff_buttons():
    class _OfferingLLM(FakeLLMProvider):
        async def generate_response(self, context):
            return "Ese dato no lo tengo. Si querés, te paso con administración."

    node = create_question_node(_OfferingLLM())

    result = await node(make_agent_state(collected_data={}))

    assert result["response_buttons"] is not None
    assert result["collected_data"]["handoff_offer_pending"] is True
