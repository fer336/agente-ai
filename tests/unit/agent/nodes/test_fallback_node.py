import pytest

from app.agent.nodes.fallback import create_fallback_node
from app.domain.repositories.llm_provider import ResponseContext
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
)
from app.infrastructure.llm.exceptions import LLMTimeoutError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_fallback_node_shows_the_main_menu_as_buttons():
    node = create_fallback_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="asdkjaslkdj"))

    buttons = result["response_buttons"]
    assert [button.id for button in buttons] == [
        MENU_APPOINTMENT_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    ]
    assert [button.title for button in buttons] == ["Turnos", "Especialidades", "Administración"]
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_fallback_node_uses_the_llm_generated_text():
    class _StubLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            return "Che, no te entendí bien. ¿Me marcás una opción?"

    node = create_fallback_node(_StubLLMProvider())

    result = await node(make_agent_state(user_message="asdkjaslkdj"))

    assert result["response_text"] == "Che, no te entendí bien. ¿Me marcás una opción?"
    assert result["response_buttons"] is not None


@pytest.mark.asyncio
async def test_fallback_node_falls_back_to_a_static_message_when_the_llm_provider_fails():
    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            raise LLMTimeoutError("boom")

    node = create_fallback_node(_ExplodingLLMProvider())

    result = await node(make_agent_state(user_message="asdkjaslkdj"))

    assert result["response_text"]
    assert [button.id for button in result["response_buttons"]] == [
        MENU_APPOINTMENT_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    ]


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
        MENU_APPOINTMENT_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        MENU_ADMIN_PAYLOAD,
    ]
    # Answering a question is not a failed turn: it must not count towards
    # the escalate-to-administración counter.
    assert "fallback_count" not in result["collected_data"]
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
async def test_first_fallback_never_tells_the_llm_to_escalate():
    # Seen live: the very first "Hola" came back as "ya intentamos un par
    # de veces...", because the escalation instruction was handed to the
    # model on every turn, not only on a repeat miss.
    seen: list[ResponseContext] = []

    class _RecordingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            seen.append(context)
            return "ok"

    node = create_fallback_node(_RecordingLLMProvider())

    await node(make_agent_state(user_message="Hola", collected_data={}))

    assert seen[0].collected_data["intentos_seguidos_sin_resolver"] == 1
    assert not any("administración" in str(value) for value in seen[0].collected_data.values())


@pytest.mark.asyncio
async def test_repeat_fallback_does_tell_the_llm_to_escalate():
    seen: list[ResponseContext] = []

    class _RecordingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            seen.append(context)
            return "ok"

    node = create_fallback_node(_RecordingLLMProvider())

    await node(make_agent_state(user_message="???", collected_data={"fallback_count": 1}))

    assert any("administración" in str(value) for value in seen[0].collected_data.values())


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
async def test_fallback_node_tells_the_llm_how_many_consecutive_attempts_happened():
    seen_contexts: list[ResponseContext] = []

    class _RecordingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            seen_contexts.append(context)
            return "ok"

    node = create_fallback_node(_RecordingLLMProvider())

    await node(make_agent_state(user_message="asdkjaslkdj", collected_data={"fallback_count": 1}))

    assert seen_contexts[0].intent == "fallback"
    assert seen_contexts[0].collected_data["intentos_seguidos_sin_resolver"] == 2
