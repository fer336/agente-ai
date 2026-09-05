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
    get_specialty_gateway,
    get_telegram_notifier,
    get_transcription_gateway,
    get_treatment_gateway,
)
from app.config.settings import Settings
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.alert_notifier import AlertNotifier
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
    PatientGateway,
    SpecialtyGateway,
    TreatmentGateway,
)
from app.domain.repositories.incident_gateway import IncidentGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.repositories.media_downloader import MediaDownloader
from app.domain.repositories.media_gateway import MediaGateway
from app.domain.repositories.transcription_gateway import TranscriptionGateway
from app.infrastructure.agent.langgraph_agent_invoker import LangGraphAgentInvoker
from app.infrastructure.dentalink.agreement_gateway import DentalinkAgreementGateway
from app.infrastructure.dentalink.appointment_gateway import DentalinkAppointmentGateway
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway
from app.infrastructure.dentalink.fake_treatment_gateway import FakeTreatmentGateway
from app.infrastructure.dentalink.patient_gateway import DentalinkPatientGateway
from app.infrastructure.dentalink.specialty_gateway import DentalinkSpecialtyGateway
from app.infrastructure.dentalink.treatment_gateway import DentalinkTreatmentGateway
from app.infrastructure.linear.fake_linear_incident_gateway import FakeLinearIncidentGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.media.fake_media_downloader import FakeMediaDownloader
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier
from app.infrastructure.transcription.fake_transcription_gateway import FakeTranscriptionGateway
from app.infrastructure.transcription.groq_transcription_gateway import GroqTranscriptionGateway
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_media_gateway import FakeYCloudMediaGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from app.infrastructure.ycloud.handoff_gateway import YCloudHandoffGateway
from app.infrastructure.ycloud.messaging_gateway import YCloudMessagingGateway


def test_get_appointment_gateway_returns_a_fake_dentalink_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )

    gateway = get_appointment_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert isinstance(gateway, AppointmentGateway)


def test_get_appointment_gateway_returns_the_same_cached_instance_across_calls():
    first = get_appointment_gateway()
    second = get_appointment_gateway()

    assert first is second


def test_get_appointment_gateway_returns_a_real_dentalink_gateway_when_token_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(
            _env_file=None,
            dentalink_access_token="dl-token",
            dentalink_default_branch_id="1",
            dentalink_default_chair_id="7",
        ),
    )

    gateway = get_appointment_gateway()

    assert isinstance(gateway, DentalinkAppointmentGateway)


def test_get_agreement_gateway_returns_a_fake_agreement_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )

    gateway = get_agreement_gateway()

    assert isinstance(gateway, FakeAgreementGateway)
    assert isinstance(gateway, AgreementGateway)


def test_get_agreement_gateway_returns_the_same_cached_instance_across_calls():
    first = get_agreement_gateway()
    second = get_agreement_gateway()

    assert first is second


def test_get_agreement_gateway_returns_a_real_dentalink_gateway_when_token_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, dentalink_access_token="dl-token"),
    )

    gateway = get_agreement_gateway()

    assert isinstance(gateway, DentalinkAgreementGateway)


def test_get_specialty_gateway_returns_a_fake_specialty_gateway_by_default():
    gateway = get_specialty_gateway()

    assert isinstance(gateway, FakeSpecialtyGateway)
    assert isinstance(gateway, SpecialtyGateway)


def test_get_specialty_gateway_returns_the_same_cached_instance_across_calls():
    first = get_specialty_gateway()
    second = get_specialty_gateway()

    assert first is second


def test_get_specialty_gateway_returns_a_real_dentalink_gateway_when_token_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, dentalink_access_token="dl-token"),
    )

    gateway = get_specialty_gateway()

    assert isinstance(gateway, DentalinkSpecialtyGateway)


def test_get_treatment_gateway_returns_a_fake_treatment_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )

    gateway = get_treatment_gateway()

    assert isinstance(gateway, FakeTreatmentGateway)
    assert isinstance(gateway, TreatmentGateway)


def test_get_treatment_gateway_returns_the_same_cached_instance_across_calls():
    first = get_treatment_gateway()
    second = get_treatment_gateway()

    assert first is second


def test_get_treatment_gateway_returns_a_real_dentalink_gateway_when_token_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, dentalink_access_token="dl-token"),
    )

    gateway = get_treatment_gateway()

    assert isinstance(gateway, DentalinkTreatmentGateway)


def test_get_messaging_gateway_returns_a_fake_ycloud_messaging_gateway():
    gateway = get_messaging_gateway()

    assert isinstance(gateway, FakeYCloudMessagingGateway)
    assert isinstance(gateway, MessagingGateway)


def test_get_messaging_gateway_returns_the_same_cached_instance_across_calls():
    first = get_messaging_gateway()
    second = get_messaging_gateway()

    assert first is second


def test_get_messaging_gateway_returns_a_real_ycloud_gateway_when_api_key_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, ycloud_api_key="yc-key"),
    )

    gateway = get_messaging_gateway()

    assert isinstance(gateway, YCloudMessagingGateway)


def test_get_human_handoff_gateway_returns_a_fake_ycloud_handoff_gateway():
    gateway = get_human_handoff_gateway()

    assert isinstance(gateway, FakeYCloudHandoffGateway)
    assert isinstance(gateway, HumanHandoffGateway)


def test_get_human_handoff_gateway_returns_the_same_cached_instance_across_calls():
    first = get_human_handoff_gateway()
    second = get_human_handoff_gateway()

    assert first is second


def test_get_human_handoff_gateway_returns_a_real_ycloud_gateway_when_api_key_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, ycloud_api_key="yc-key"),
    )

    gateway = get_human_handoff_gateway()

    assert isinstance(gateway, YCloudHandoffGateway)


def test_get_patient_gateway_returns_a_fake_patient_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )

    gateway = get_patient_gateway()

    assert isinstance(gateway, FakePatientGateway)
    assert isinstance(gateway, PatientGateway)


def test_get_patient_gateway_returns_the_same_cached_instance_across_calls():
    first = get_patient_gateway()
    second = get_patient_gateway()

    assert first is second


def test_get_patient_gateway_returns_a_real_dentalink_gateway_when_token_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, dentalink_access_token="dl-token"),
    )

    gateway = get_patient_gateway()

    assert isinstance(gateway, DentalinkPatientGateway)


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


def test_get_transcription_gateway_returns_a_fake_transcription_gateway_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )

    gateway = get_transcription_gateway()

    assert isinstance(gateway, FakeTranscriptionGateway)
    assert isinstance(gateway, TranscriptionGateway)


def test_get_transcription_gateway_returns_the_same_cached_instance_across_calls():
    first = get_transcription_gateway()
    second = get_transcription_gateway()

    assert first is second


def test_get_transcription_gateway_returns_a_real_groq_gateway_when_api_key_is_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings",
        lambda: Settings(_env_file=None, groq_api_key="groq-key"),
    )

    gateway = get_transcription_gateway()

    assert isinstance(gateway, GroqTranscriptionGateway)


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
