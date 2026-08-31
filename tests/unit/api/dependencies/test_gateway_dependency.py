from app.api.dependencies.gateways import (
    get_agent_invoker,
    get_agreement_gateway,
    get_appointment_gateway,
    get_human_handoff_gateway,
    get_linear_gateway,
    get_llm_provider,
    get_media_downloader,
    get_media_gateway,
    get_messaging_gateway,
    get_patient_gateway,
    get_telegram_notifier,
    get_transcription_gateway,
)
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.alert_notifier import AlertNotifier
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
    PatientGateway,
)
from app.domain.repositories.incident_gateway import IncidentGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.repositories.media_downloader import MediaDownloader
from app.domain.repositories.media_gateway import MediaGateway
from app.domain.repositories.transcription_gateway import TranscriptionGateway
from app.infrastructure.agent.langgraph_agent_invoker import LangGraphAgentInvoker
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.linear.fake_linear_incident_gateway import FakeLinearIncidentGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.media.fake_media_downloader import FakeMediaDownloader
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier
from app.infrastructure.transcription.fake_transcription_gateway import FakeTranscriptionGateway
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_media_gateway import FakeYCloudMediaGateway
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


def test_get_transcription_gateway_returns_a_fake_transcription_gateway():
    gateway = get_transcription_gateway()

    assert isinstance(gateway, FakeTranscriptionGateway)
    assert isinstance(gateway, TranscriptionGateway)


def test_get_transcription_gateway_returns_the_same_cached_instance_across_calls():
    first = get_transcription_gateway()
    second = get_transcription_gateway()

    assert first is second


def test_get_media_gateway_returns_a_fake_ycloud_media_gateway():
    gateway = get_media_gateway()

    assert isinstance(gateway, FakeYCloudMediaGateway)
    assert isinstance(gateway, MediaGateway)


def test_get_media_gateway_returns_the_same_cached_instance_across_calls():
    first = get_media_gateway()
    second = get_media_gateway()

    assert first is second


def test_get_media_downloader_returns_a_fake_media_downloader():
    downloader = get_media_downloader()

    assert isinstance(downloader, FakeMediaDownloader)
    assert isinstance(downloader, MediaDownloader)


def test_get_media_downloader_returns_the_same_cached_instance_across_calls():
    first = get_media_downloader()
    second = get_media_downloader()

    assert first is second


def test_get_telegram_notifier_returns_a_fake_telegram_alert_notifier():
    notifier = get_telegram_notifier()

    assert isinstance(notifier, FakeTelegramAlertNotifier)
    assert isinstance(notifier, AlertNotifier)


def test_get_telegram_notifier_returns_the_same_cached_instance_across_calls():
    first = get_telegram_notifier()
    second = get_telegram_notifier()

    assert first is second


def test_get_linear_gateway_returns_a_fake_linear_incident_gateway():
    gateway = get_linear_gateway()

    assert isinstance(gateway, FakeLinearIncidentGateway)
    assert isinstance(gateway, IncidentGateway)


def test_get_linear_gateway_returns_the_same_cached_instance_across_calls():
    first = get_linear_gateway()
    second = get_linear_gateway()

    assert first is second
