from functools import lru_cache

from app.domain.repositories.gateways import (
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
)
from app.domain.repositories.llm_provider import LLMProvider
from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway


@lru_cache
def _get_fake_dentalink_gateway() -> FakeDentalinkGateway:
    return FakeDentalinkGateway()


def get_appointment_gateway() -> AppointmentGateway:
    """FastAPI dependency providing the `AppointmentGateway` port.

    Returns the in-memory `FakeDentalinkGateway` for now. This is the swap
    point for a real Dentalink adapter in a later change — callers only
    depend on the `AppointmentGateway` Protocol.
    """
    return _get_fake_dentalink_gateway()


@lru_cache
def _get_fake_whatsapp_gateway() -> FakeWhatsAppGateway:
    return FakeWhatsAppGateway()


def get_messaging_gateway() -> MessagingGateway:
    """FastAPI dependency providing the `MessagingGateway` port.

    Returns the in-memory `FakeWhatsAppGateway` for now. This is the swap
    point for a real WhatsApp adapter in a later change — callers only
    depend on the `MessagingGateway` Protocol.
    """
    return _get_fake_whatsapp_gateway()


@lru_cache
def _get_fake_chatwoot_gateway() -> FakeChatwootGateway:
    return FakeChatwootGateway()


def get_human_handoff_gateway() -> HumanHandoffGateway:
    """FastAPI dependency providing the `HumanHandoffGateway` port.

    Returns the in-memory `FakeChatwootGateway` for now. This is the swap
    point for a real Chatwoot adapter in a later change — callers only
    depend on the `HumanHandoffGateway` Protocol.
    """
    return _get_fake_chatwoot_gateway()


@lru_cache
def _get_fake_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency providing the `LLMProvider` port.

    Returns the in-memory `FakeLLMProvider` for now. This is the swap point
    for a real LLM adapter in a later change — callers only depend on the
    `LLMProvider` Protocol.
    """
    return _get_fake_llm_provider()
