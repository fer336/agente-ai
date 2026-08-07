"""Shared fake-gateway factory functions for tests.

Plain factory functions (not `@pytest.fixture`s) — fakes have no
setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline `Fake*()` construction these replace.
"""

from app.domain.entities.appointment_slot import AppointmentSlot
from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway


def make_dentalink_gateway(
    available_slots: list[AppointmentSlot] | None = None,
) -> FakeDentalinkGateway:
    return FakeDentalinkGateway(available_slots=available_slots)


def make_chatwoot_gateway() -> FakeChatwootGateway:
    return FakeChatwootGateway()


def make_whatsapp_gateway() -> FakeWhatsAppGateway:
    return FakeWhatsAppGateway()


def make_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()
