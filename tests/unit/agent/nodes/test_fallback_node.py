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
