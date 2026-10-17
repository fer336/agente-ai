import pytest

from app.agent.nodes.fallback import OUT_OF_SCOPE_MESSAGE, create_fallback_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import ResponseContext
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.llm.exceptions import LLMTimeoutError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_out_of_scope_reply_is_the_approved_fixed_text():
    node = create_fallback_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="asdkjaslkdj"))

    assert result["response_text"] == OUT_OF_SCOPE_MESSAGE
    assert OUT_OF_SCOPE_MESSAGE == (
        "Disculpame, con eso no te puedo ayudar por acá 🙏 Solo puedo guiarte con la "
        "información del menú principal.\n"
        "Si querés sacar un turno, tocá *Agendar una cita*. Y si necesitás otra cosa, "
        "escribile a *Administración* o volvé al *Menú*."
    )
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_out_of_scope_reply_has_exactly_the_three_buttons():
    node = create_fallback_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="asdkjaslkdj"))

    buttons = result["response_buttons"]
    assert [(button.id, button.title) for button in buttons] == [
        (OPERATION_CREATE_PAYLOAD, "📅 Agendar una cita"),
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
        (MENU_MAIN_PAYLOAD, "📋 Menú principal"),
    ]
    # WhatsApp: at most 3 reply buttons, titles up to 20 characters.
    assert len(buttons) <= 3
    assert all(len(button.title.encode("utf-16-le")) // 2 <= 20 for button in buttons)


@pytest.mark.asyncio
async def test_out_of_scope_reply_never_calls_the_llm_for_text():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            raise AssertionError("the out-of-scope text is fixed: no LLM text generation")

    node = create_fallback_node(_ExplodingLLMProvider())

    for count in (0, 1, 5):
        result = await node(
            make_agent_state(
                user_message="dame una receta", collected_data={"fallback_count": count}
            )
        )
        assert result["response_text"] == OUT_OF_SCOPE_MESSAGE


@pytest.mark.asyncio
async def test_the_main_menu_button_carries_the_payload_that_routes_to_the_main_menu():
    node = create_fallback_node(FakeLLMProvider())
    result = await node(make_agent_state(user_message="asdkjaslkdj"))
    resolver = create_resolve_interaction_node(FakeLLMProvider())

    tapped = next(b for b in result["response_buttons"] if b.title == "📋 Menú principal")
    routed = await resolver(make_agent_state(button_payload=tapped.id))

    assert tapped.id == MENU_MAIN_PAYLOAD
    assert routed["intent"] == "appointment"


@pytest.mark.asyncio
async def test_fallback_node_tracks_consecutive_attempts_in_collected_data():
    node = create_fallback_node(FakeLLMProvider())

    first = await node(make_agent_state(user_message="asdkjaslkdj", collected_data={}))
    assert first["collected_data"]["fallback_count"] == 1

    second = await node(
        make_agent_state(user_message="asdkjaslkdj", collected_data=first["collected_data"])
    )
    assert second["collected_data"]["fallback_count"] == 2


@pytest.mark.asyncio
async def test_a_pending_answer_is_delivered_instead_of_the_did_not_understand_text():
    # `resolve_interaction` already had the model answer the question; this
    # node just delivers it, keeping the menu buttons as a way forward.
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            raise AssertionError("must not re-generate when an answer is already available")

    node = create_fallback_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(
            user_message="¿atienden los sábados?",
            collected_data={"pending_answer": "Sí, atendemos los sábados a la mañana."},
        )
    )

    assert result["response_text"] == "Sí, atendemos los sábados a la mañana."
    assert [button.id for button in result["response_buttons"]] == [
        OPERATION_CREATE_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    ]
    # Answering a question is not a failed turn: it must not count towards
    # the escalate-to-administración counter.
    assert "fallback_count" not in result["collected_data"]
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "¿dónde queda la clínica?",
        "donde estan ubicados",
        "como llego",
        "cual es la dirección",
    ],
)
async def test_a_location_question_sends_the_native_location_card(message: str) -> None:
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            raise AssertionError("a location question must never go through the LLM")

    node = create_fallback_node(_ExplodingLLMProvider())

    result = await node(make_agent_state(user_message=message))

    location = result["response_location"]
    assert location is not None
    assert location.name == "Smiling Pilar"
    assert location.address == "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"
    assert location.latitude == pytest.approx(-34.437762)
    assert location.longitude == pytest.approx(-58.7917857)
    assert result["response_buttons"] is None


@pytest.mark.asyncio
async def test_a_location_question_clears_a_stale_pending_answer():
    node = create_fallback_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="como llego",
            collected_data={"pending_answer": "algo viejo"},
        )
    )

    assert "pending_answer" not in result["collected_data"]
    assert result["response_location"] is not None


@pytest.mark.asyncio
async def test_fallback_delivers_a_pending_answer_without_a_mid_conversation_greeting():
    node = create_fallback_node(FakeLLMProvider())
    state = make_agent_state(
        recent_messages=[
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Hola! Soy el asistente."},
            {"role": "user", "content": "¿atienden particulares?"},
        ],
        collected_data={"pending_answer": "Hola! Sí, atendemos particulares."},
    )

    result = await node(state)

    assert result["response_text"] == "Sí, atendemos particulares."


@pytest.mark.asyncio
async def test_fallback_answer_offering_administration_carries_the_handoff_buttons():
    node = create_fallback_node(FakeLLMProvider())
    state = make_agent_state(
        collected_data={
            "pending_answer": "Si querés, puedo pasarte con administración. ¿Te parece bien?"
        },
    )

    result = await node(state)

    assert [b.id for b in result["response_buttons"]] == [MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD]
    assert result["collected_data"]["handoff_offer_pending"] is True


def _capturing_provider(captured: list[ResponseContext]) -> FakeLLMProvider:
    class _CapturingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            captured.append(context)
            return "ok"

    return _CapturingLLMProvider()


@pytest.mark.asyncio
async def test_after_the_welcome_menu_the_llm_is_told_to_ask_for_a_menu_option():
    captured: list[ResponseContext] = []
    node = create_fallback_node(_capturing_provider(captured))

    await node(
        make_agent_state(
            user_message="Holaa",
            recent_messages=[
                {"role": "assistant", "content": WELCOME_TEXT},
                {"role": "user", "content": "Holaa"},
            ],
        )
    )

    context = captured[0].collected_data
    assert "menú de bienvenida" in str(context["situacion"])
    assert "saludá" not in str(context["instruccion"])
    assert "elija una de las opciones del menú" in str(context["instruccion"])


@pytest.mark.asyncio
async def test_without_a_recent_welcome_menu_the_out_of_scope_text_is_used():
    captured: list[ResponseContext] = []
    node = create_fallback_node(_capturing_provider(captured))

    result = await node(
        make_agent_state(
            user_message="Holaa",
            recent_messages=[
                {"role": "assistant", "content": WELCOME_TEXT},
                {"role": "user", "content": "quiero un turno"},
                {"role": "assistant", "content": "Elegí una especialidad"},
                {"role": "user", "content": "Holaa"},
            ],
        )
    )

    assert captured == []
    assert result["response_text"] == OUT_OF_SCOPE_MESSAGE
    assert result.get("response_list") is None


@pytest.mark.asyncio
async def test_after_the_welcome_menu_the_static_text_asks_for_a_menu_option_when_the_llm_fails():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            raise LLMTimeoutError("boom")

    node = create_fallback_node(_ExplodingLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Holaa",
            recent_messages=[
                {"role": "assistant", "content": WELCOME_TEXT},
                {"role": "user", "content": "Holaa"},
            ],
        )
    )

    assert not result["response_text"].startswith("¡Hola")
    assert "opciones del menú" in result["response_text"]


@pytest.mark.asyncio
async def test_after_the_welcome_menu_the_welcome_list_is_re_attached_instead_of_buttons():
    node = create_fallback_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="Holaa",
            recent_messages=[
                {"role": "assistant", "content": WELCOME_TEXT},
                {"role": "user", "content": "Holaa"},
            ],
        )
    )

    assert result["response_list"] is WELCOME_LIST
    assert result["response_buttons"] is None


_AFTER_WELCOME = [
    {"role": "assistant", "content": WELCOME_TEXT},
    {"role": "user", "content": "Holaa"},
]


@pytest.mark.asyncio
async def test_after_the_welcome_menu_the_llm_gets_its_own_intent_not_fallback():
    captured: list[ResponseContext] = []
    node = create_fallback_node(_capturing_provider(captured))

    await node(make_agent_state(user_message="Holaa", recent_messages=_AFTER_WELCOME))

    assert captured[0].intent == "welcome_menu_reminder"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_text",
    [
        "Perdón, no te entendí bien. Para poder continuar, elegí una opción del menú.",
        "Disculpá, no entendí tu mensaje. Elegí una opción del menú.",
    ],
)
async def test_after_the_welcome_menu_a_did_not_understand_reply_is_replaced_by_the_static_text(
    model_text,
):
    class _ApologisingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            return model_text

    node = create_fallback_node(_ApologisingLLMProvider())

    result = await node(make_agent_state(user_message="Holaa", recent_messages=_AFTER_WELCOME))

    assert result["response_text"] == (
        "Para poder continuar, elegí por favor una de las opciones del menú tocando el "
        "botón de abajo 👇"
    )


@pytest.mark.asyncio
async def test_after_the_welcome_menu_a_clean_llm_reply_is_kept():
    class _StubLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            return "Para seguir, elegí una de las opciones del menú 👇"

    node = create_fallback_node(_StubLLMProvider())

    result = await node(make_agent_state(user_message="Holaa", recent_messages=_AFTER_WELCOME))

    assert result["response_text"] == "Para seguir, elegí una de las opciones del menú 👇"
