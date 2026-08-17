from app.api.dependencies.gateways import (
    get_agent_invoker,
    get_agreement_gateway,
    get_appointment_gateway,
    get_human_handoff_gateway,
    get_llm_provider,
    get_messaging_gateway,
    get_patient_gateway,
)
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
    PatientGateway,
)
from app.domain.repositories.llm_provider import LLMProvider
from app.infrastructure.agent.langgraph_agent_invoker import LangGraphAgentInvoker
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway


def test_get_appointment_gateway_returns_a_fake_dentalink_gateway():
    gateway = get_appointment_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert isinstance(gateway, AppointmentGateway)


def test_get_appointment_gateway_returns_the_same_cached_instance_across_calls():
    first = get_appointment_gateway()
    second = get_appointment_gateway()

    assert first is second


def test_get_agreement_gateway_returns_a_fake_agreement_gateway():
    gateway = get_agreement_gateway()

    assert isinstance(gateway, FakeAgreementGateway)
    assert isinstance(gateway, AgreementGateway)


def test_get_agreement_gateway_returns_the_same_cached_instance_across_calls():
    first = get_agreement_gateway()
    second = get_agreement_gateway()

    assert first is second


def test_get_messaging_gateway_returns_a_fake_ycloud_messaging_gateway():
    gateway = get_messaging_gateway()

    assert isinstance(gateway, FakeYCloudMessagingGateway)
    assert isinstance(gateway, MessagingGateway)


def test_get_messaging_gateway_returns_the_same_cached_instance_across_calls():
    first = get_messaging_gateway()
    second = get_messaging_gateway()

    assert first is second


def test_get_human_handoff_gateway_returns_a_fake_ycloud_handoff_gateway():
    gateway = get_human_handoff_gateway()

    assert isinstance(gateway, FakeYCloudHandoffGateway)
    assert isinstance(gateway, HumanHandoffGateway)


def test_get_human_handoff_gateway_returns_the_same_cached_instance_across_calls():
    first = get_human_handoff_gateway()
    second = get_human_handoff_gateway()

    assert first is second


def test_get_patient_gateway_returns_a_fake_patient_gateway():
    gateway = get_patient_gateway()

    assert isinstance(gateway, FakePatientGateway)
    assert isinstance(gateway, PatientGateway)


def test_get_patient_gateway_returns_the_same_cached_instance_across_calls():
    first = get_patient_gateway()
    second = get_patient_gateway()

    assert first is second


def test_get_llm_provider_returns_a_fake_llm_provider():
    provider = get_llm_provider()

    assert isinstance(provider, FakeLLMProvider)
    assert isinstance(provider, LLMProvider)


def test_get_llm_provider_returns_the_same_cached_instance_across_calls():
    first = get_llm_provider()
    second = get_llm_provider()

    assert first is second


def test_get_agent_invoker_returns_a_langgraph_agent_invoker():
    invoker = get_agent_invoker()

    assert isinstance(invoker, LangGraphAgentInvoker)
    assert isinstance(invoker, AgentInvoker)


def test_get_agent_invoker_returns_the_same_cached_instance_across_calls():
    first = get_agent_invoker()
    second = get_agent_invoker()

    assert first is second
