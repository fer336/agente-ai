from app.api.dependencies.gateways import (
    get_agent_invoker,
    get_appointment_gateway,
    get_chatwoot_conversation_gateway,
    get_human_handoff_gateway,
    get_llm_provider,
    get_messaging_gateway,
)
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.gateways import (
    AppointmentGateway,
    ChatwootConversationGateway,
    HumanHandoffGateway,
    MessagingGateway,
)
from app.domain.repositories.llm_provider import LLMProvider
from app.infrastructure.agent.not_implemented_agent_invoker import NotImplementedAgentInvoker
from app.infrastructure.chatwoot.fake_chatwoot_conversation_gateway import (
    FakeChatwootConversationGateway,
)
from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway


def test_get_appointment_gateway_returns_a_fake_dentalink_gateway():
    gateway = get_appointment_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert isinstance(gateway, AppointmentGateway)


def test_get_appointment_gateway_returns_the_same_cached_instance_across_calls():
    first = get_appointment_gateway()
    second = get_appointment_gateway()

    assert first is second


def test_get_messaging_gateway_returns_a_fake_whatsapp_gateway():
    gateway = get_messaging_gateway()

    assert isinstance(gateway, FakeWhatsAppGateway)
    assert isinstance(gateway, MessagingGateway)


def test_get_messaging_gateway_returns_the_same_cached_instance_across_calls():
    first = get_messaging_gateway()
    second = get_messaging_gateway()

    assert first is second


def test_get_human_handoff_gateway_returns_a_fake_chatwoot_gateway():
    gateway = get_human_handoff_gateway()

    assert isinstance(gateway, FakeChatwootGateway)
    assert isinstance(gateway, HumanHandoffGateway)


def test_get_human_handoff_gateway_returns_the_same_cached_instance_across_calls():
    first = get_human_handoff_gateway()
    second = get_human_handoff_gateway()

    assert first is second


def test_get_llm_provider_returns_a_fake_llm_provider():
    provider = get_llm_provider()

    assert isinstance(provider, FakeLLMProvider)
    assert isinstance(provider, LLMProvider)


def test_get_llm_provider_returns_the_same_cached_instance_across_calls():
    first = get_llm_provider()
    second = get_llm_provider()

    assert first is second


def test_get_agent_invoker_returns_a_not_implemented_agent_invoker():
    invoker = get_agent_invoker()

    assert isinstance(invoker, NotImplementedAgentInvoker)
    assert isinstance(invoker, AgentInvoker)


def test_get_agent_invoker_returns_the_same_cached_instance_across_calls():
    first = get_agent_invoker()
    second = get_agent_invoker()

    assert first is second


def test_get_chatwoot_conversation_gateway_returns_a_fake_chatwoot_conversation_gateway():
    gateway = get_chatwoot_conversation_gateway()

    assert isinstance(gateway, FakeChatwootConversationGateway)
    assert isinstance(gateway, ChatwootConversationGateway)


def test_get_chatwoot_conversation_gateway_returns_the_same_cached_instance_across_calls():
    first = get_chatwoot_conversation_gateway()
    second = get_chatwoot_conversation_gateway()

    assert first is second
