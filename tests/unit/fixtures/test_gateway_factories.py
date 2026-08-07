import pytest

from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway
from tests.fixtures.gateways import (
    make_chatwoot_gateway,
    make_dentalink_gateway,
    make_llm_provider,
    make_whatsapp_gateway,
)
from tests.fixtures.seed_objects import make_slot


def test_make_dentalink_gateway_returns_a_fresh_fake_with_no_slots_by_default():
    gateway = make_dentalink_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert gateway._available_slots == []


def test_make_dentalink_gateway_accepts_available_slots_override():
    slot = make_slot()

    gateway = make_dentalink_gateway(available_slots=[slot])

    assert gateway._available_slots == [slot]


@pytest.mark.asyncio
async def test_make_chatwoot_gateway_returns_a_fresh_fake_chatwoot_gateway():
    gateway = make_chatwoot_gateway()

    assert isinstance(gateway, FakeChatwootGateway)
    assert gateway.handoff_requests == []


@pytest.mark.asyncio
async def test_make_whatsapp_gateway_returns_a_fresh_fake_whatsapp_gateway():
    gateway = make_whatsapp_gateway()

    assert isinstance(gateway, FakeWhatsAppGateway)
    assert gateway.sent_messages == []


@pytest.mark.asyncio
async def test_make_llm_provider_returns_a_fresh_fake_llm_provider():
    provider = make_llm_provider()

    assert isinstance(provider, FakeLLMProvider)
    result = await provider.classify_intent("Hola", context={})
    assert result.intent == "unknown"
