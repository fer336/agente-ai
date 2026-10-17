import pytest

from app.agent.nodes.fallback import OUT_OF_SCOPE_MESSAGE, create_fallback_node
from app.agent.nodes.question import create_question_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import UnderstandingResult
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


class _ScriptedLLM(FakeLLMProvider):
    """Understands every message as the given intent, like the real model sometimes does."""

    def __init__(self, intent: str, faq_topic_id: str | None = None) -> None:
        self._intent = intent
        self._faq_topic_id = faq_topic_id

    async def understand(self, message, context):  # type: ignore[no-untyped-def]
        return UnderstandingResult(
            intent=self._intent, confidence=0.9, faq_topic_id=self._faq_topic_id
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Hola", "Buenas tardes", "Hola, quiero info", "HOLA"])
@pytest.mark.parametrize("model_intent", ["question", "faq_topic", "unknown", "appointment"])
async def test_an_idle_greeting_ends_in_the_welcome_menu_whatever_the_model_says(
    message: str, model_intent: str
) -> None:
    llm = _ScriptedLLM(model_intent)
    routed = await create_resolve_interaction_node(llm)(make_agent_state(user_message=message))
    assert routed["intent"] == "unknown"

    reply = await create_fallback_node(llm)(
        make_agent_state(user_message=message, collected_data=routed.get("collected_data", {}))
    )

    assert reply["response_text"] == WELCOME_TEXT
    assert reply["response_list"] == WELCOME_LIST
    assert reply["response_buttons"] is None
    assert reply["requires_handoff"] is False
    assert "fallback_count" not in reply["collected_data"]


@pytest.mark.asyncio
async def test_a_greeting_inside_a_stage_stays_with_the_stage() -> None:
    node = create_resolve_interaction_node(FakeLLMProvider())

    routed = await node(
        make_agent_state(user_message="Hola", collected_data={"stage": "awaiting_identification"})
    )

    assert routed["intent"] == "appointment"


@pytest.mark.asyncio
async def test_a_greeting_that_also_asks_for_an_appointment_keeps_its_routing() -> None:
    node = create_resolve_interaction_node(FakeLLMProvider())

    routed = await node(make_agent_state(user_message="Hola, quiero un turno"))

    assert routed["intent"] == "appointment"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "¿Cómo se hace un flan casero?",
        "¿Cómo hago un bucle for en JavaScript?",
        "¿A qué hora abre el banco?",
        "diagnóstico por foto",
    ],
)
async def test_an_off_topic_question_the_model_labels_faq_gets_the_fixed_out_of_scope_text(
    message: str,
) -> None:
    llm = _ScriptedLLM("faq_topic")
    routed = await create_resolve_interaction_node(llm)(make_agent_state(user_message=message))
    assert routed["intent"] == "question"

    reply = await create_question_node(llm)(
        make_agent_state(user_message=message, collected_data=routed.get("collected_data", {}))
    )

    assert reply["response_text"] == OUT_OF_SCOPE_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["¿Cuánto cuesta un implante?", "Consultas frecuentes", "quiero info sobre precios"],
)
async def test_a_price_or_general_info_request_still_reaches_the_faq_menu(message: str) -> None:
    routed = await create_resolve_interaction_node(_ScriptedLLM("faq_topic"))(
        make_agent_state(user_message=message)
    )

    assert routed["intent"] == "faq_topic"


@pytest.mark.asyncio
async def test_a_topic_id_named_by_the_model_keeps_the_faq_route() -> None:
    routed = await create_resolve_interaction_node(_ScriptedLLM("faq_topic", "blanqueamiento"))(
        make_agent_state(user_message="quiero aclararme un poco la sonrisa")
    )

    assert routed["intent"] == "faq_topic"
    assert routed["collected_data"]["faq_topic_id"] == "blanqueamiento"
