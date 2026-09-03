import pytest

from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import (
    make_agreement_gateway,
    make_dentalink_gateway,
    make_llm_provider,
    make_specialty_gateway,
    make_ycloud_handoff_gateway,
    make_ycloud_messaging_gateway,
)
from tests.fixtures.seed_objects import make_agreement, make_professional, make_slot, make_specialty


def test_make_dentalink_gateway_returns_a_fresh_fake_with_no_slots_by_default():
    gateway = make_dentalink_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert gateway._available_slots == []


def test_make_dentalink_gateway_accepts_available_slots_override():
    slot = make_slot()

    gateway = make_dentalink_gateway(available_slots=[slot])

    assert gateway._available_slots == [slot]


def test_make_dentalink_gateway_accepts_professionals_override():
    professional = make_professional()

    gateway = make_dentalink_gateway(professionals=[professional])

    assert gateway._professionals == [professional]


@pytest.mark.asyncio
async def test_make_agreement_gateway_returns_a_fresh_fake_with_no_agreements_by_default():
    gateway = make_agreement_gateway()

    assert isinstance(gateway, FakeAgreementGateway)
    assert await gateway.list_agreements() == []


@pytest.mark.asyncio
async def test_make_agreement_gateway_accepts_agreements_override():
    agreement = make_agreement()

    gateway = make_agreement_gateway(agreements=[agreement])

    assert await gateway.list_agreements() == [agreement]


@pytest.mark.asyncio
async def test_make_specialty_gateway_returns_a_fresh_fake_with_no_specialties_by_default():
    gateway = make_specialty_gateway()

    assert isinstance(gateway, FakeSpecialtyGateway)
    assert await gateway.list_specialties() == []


@pytest.mark.asyncio
async def test_make_specialty_gateway_accepts_specialties_override():
    specialty = make_specialty()

    gateway = make_specialty_gateway(specialties=[specialty])

    assert await gateway.list_specialties() == [specialty]


@pytest.mark.asyncio
async def test_make_ycloud_handoff_gateway_returns_a_fresh_fake_handoff_gateway():
    gateway = make_ycloud_handoff_gateway()

    assert isinstance(gateway, FakeYCloudHandoffGateway)
    assert gateway.handoff_requests == []


@pytest.mark.asyncio
async def test_make_ycloud_messaging_gateway_returns_a_fresh_fake_messaging_gateway():
    gateway = make_ycloud_messaging_gateway()

    assert isinstance(gateway, FakeYCloudMessagingGateway)
    assert gateway.sent_messages == []


@pytest.mark.asyncio
async def test_make_llm_provider_returns_a_fresh_fake_llm_provider():
    provider = make_llm_provider()

    assert isinstance(provider, FakeLLMProvider)
    result = await provider.classify_intent("Hola", context={})
    assert result.intent == "unknown"
