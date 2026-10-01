import pytest

from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS, HANDOFF_OFFER_KEY
from app.agent.nodes.payment_admin import PAYMENT_ADMIN_STATIC_MESSAGE, create_payment_admin_node
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


class _RecordingLLMProvider(FakeLLMProvider):
    def __init__(self) -> None:
        self.contexts: list[ResponseContext] = []

    async def generate_response(self, context: ResponseContext) -> str:
        self.contexts.append(context)
        return "Eso lo manejan directamente en Administración."


class _FailingLLMProvider(FakeLLMProvider):
    async def generate_response(self, context: ResponseContext) -> str:
        raise LLMProviderError("boom")


@pytest.mark.asyncio
async def test_the_llm_wording_is_used_with_the_administration_instruction():
    provider = _RecordingLLMProvider()

    result = await create_payment_admin_node(provider)(make_agent_state())

    assert result["response_text"] == "Eso lo manejan directamente en Administración."
    context = provider.contexts[0]
    assert context.intent == "payment_admin"
    assert "Administración" in str(context.collected_data["instruccion"])
    assert "situacion" in context.collected_data


@pytest.mark.asyncio
async def test_the_static_message_is_the_fallback_when_the_llm_fails():
    result = await create_payment_admin_node(_FailingLLMProvider())(make_agent_state())

    assert result["response_text"] == PAYMENT_ADMIN_STATIC_MESSAGE
    assert PAYMENT_ADMIN_STATIC_MESSAGE == (
        "Los pagos, anticipos y demás precios se manejan directamente con Administración. "
        "Si querés, te comunico con ellos."
    )


@pytest.mark.asyncio
async def test_it_offers_the_handoff_and_keeps_the_booking_data():
    collected = {"stage": "awaiting_slot_selection", "chosen_professional_id": "p1"}

    result = await create_payment_admin_node(FakeLLMProvider())(
        make_agent_state(collected_data=collected)
    )

    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS
    assert result["requires_handoff"] is False
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"
    assert result["collected_data"][HANDOFF_OFFER_KEY] is True


@pytest.mark.asyncio
async def test_the_fake_llm_gives_a_deterministic_administration_text():
    result = await create_payment_admin_node(FakeLLMProvider())(make_agent_state())

    assert "Administración" in result["response_text"]
