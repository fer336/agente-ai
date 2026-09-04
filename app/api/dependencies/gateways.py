from functools import lru_cache

from app.api.dependencies.checkpointer import get_agent_checkpointer
from app.api.dependencies.redis import get_shared_redis_client
from app.api.dependencies.repositories import (
    open_sqlalchemy_agent_repositories,
    open_sqlalchemy_proposal_repositories,
    open_sqlalchemy_trace_repositories,
)
from app.application.messages.send_reply import SendReplyUseCase
from app.config.settings import get_settings
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
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway
from app.infrastructure.dentalink.fake_treatment_gateway import FakeTreatmentGateway
from app.infrastructure.dentalink.patient_gateway import DentalinkPatientGateway
from app.infrastructure.dentalink.specialty_gateway import DentalinkSpecialtyGateway
from app.infrastructure.dentalink.treatment_gateway import DentalinkTreatmentGateway
from app.infrastructure.linear.fake_linear_incident_gateway import FakeLinearIncidentGateway
from app.infrastructure.llm.client import OpenAICompatibleLLMClient
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.llm.openai_compatible_llm_provider import OpenAICompatibleLLMProvider
from app.infrastructure.media.fake_media_downloader import FakeMediaDownloader
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier
from app.infrastructure.transcription.fake_transcription_gateway import FakeTranscriptionGateway
from app.infrastructure.ycloud.client import YCloudClient
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_media_gateway import FakeYCloudMediaGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from app.infrastructure.ycloud.handoff_gateway import YCloudHandoffGateway
from app.infrastructure.ycloud.messaging_gateway import YCloudMessagingGateway


@lru_cache
def _get_fake_dentalink_gateway() -> FakeDentalinkGateway:
    return FakeDentalinkGateway()


@lru_cache
def _get_real_appointment_gateway() -> DentalinkAppointmentGateway:
    settings = get_settings()
    return DentalinkAppointmentGateway(
        _get_dentalink_client(),
        default_branch_id=settings.dentalink_default_branch_id,
        default_chair_id=settings.dentalink_default_chair_id,
        default_duration_minutes=settings.dentalink_default_duration_minutes,
    )


def get_appointment_gateway() -> AppointmentGateway:
    """FastAPI dependency providing the `AppointmentGateway` port.

    Returns the real, `httpx`-based `DentalinkAppointmentGateway` whenever
    `settings.dentalink_access_token` is configured, else the in-memory
    `FakeDentalinkGateway` — same conditional pattern as
    `get_specialty_gateway` below. Callers only depend on the
    `AppointmentGateway` Protocol.
    """
    if get_settings().dentalink_access_token:
        return _get_real_appointment_gateway()
    return _get_fake_dentalink_gateway()


@lru_cache
def _get_fake_agreement_gateway() -> FakeAgreementGateway:
    return FakeAgreementGateway()


@lru_cache
def _get_real_agreement_gateway() -> DentalinkAgreementGateway:
    return DentalinkAgreementGateway(_get_dentalink_client())


def get_agreement_gateway() -> AgreementGateway:
    """FastAPI dependency providing the `AgreementGateway` port.

    Returns the real, `httpx`-based `DentalinkAgreementGateway` whenever
    `settings.dentalink_access_token` is configured, else the in-memory
    `FakeAgreementGateway` — same conditional pattern as
    `get_specialty_gateway` below. Callers only depend on the
    `AgreementGateway` Protocol.
    """
    if get_settings().dentalink_access_token:
        return _get_real_agreement_gateway()
    return _get_fake_agreement_gateway()


@lru_cache
def _get_fake_specialty_gateway() -> FakeSpecialtyGateway:
    return FakeSpecialtyGateway()


@lru_cache
def _get_dentalink_client() -> DentalinkClient:
    settings = get_settings()
    return DentalinkClient(
        base_url=settings.dentalink_api_url,
        access_token=settings.dentalink_access_token,
        timeout_seconds=settings.dentalink_timeout_seconds,
    )


@lru_cache
def _get_dentalink_specialty_gateway() -> DentalinkSpecialtyGateway:
    return DentalinkSpecialtyGateway(_get_dentalink_client())


def get_specialty_gateway() -> SpecialtyGateway:
    """FastAPI dependency providing the `SpecialtyGateway` port.

    Returns the real, `httpx`-based `DentalinkSpecialtyGateway` whenever
    `settings.dentalink_access_token` is configured, else the in-memory
    `FakeSpecialtyGateway` — callers only depend on the `SpecialtyGateway`
    Protocol. Same conditional pattern as `get_appointment_gateway`/
    `get_agreement_gateway`/`get_patient_gateway` above.
    """
    if get_settings().dentalink_access_token:
        return _get_dentalink_specialty_gateway()
    return _get_fake_specialty_gateway()


@lru_cache
def _get_fake_treatment_gateway() -> FakeTreatmentGateway:
    return FakeTreatmentGateway()


@lru_cache
def _get_real_treatment_gateway() -> DentalinkTreatmentGateway:
    return DentalinkTreatmentGateway(_get_dentalink_client())


def get_treatment_gateway() -> TreatmentGateway:
    """FastAPI dependency providing the `TreatmentGateway` port.

    Returns the real, `httpx`-based `DentalinkTreatmentGateway` whenever
    `settings.dentalink_access_token` is configured, else the in-memory
    `FakeTreatmentGateway` — same conditional pattern as
    `get_specialty_gateway` above.
    """
    if get_settings().dentalink_access_token:
        return _get_real_treatment_gateway()
    return _get_fake_treatment_gateway()


@lru_cache
def _get_fake_patient_gateway() -> FakePatientGateway:
    return FakePatientGateway()


@lru_cache
def _get_real_patient_gateway() -> DentalinkPatientGateway:
    return DentalinkPatientGateway(_get_dentalink_client())


def get_patient_gateway() -> PatientGateway:
    """FastAPI dependency providing the `PatientGateway` port.

    Returns the real, `httpx`-based `DentalinkPatientGateway` whenever
    `settings.dentalink_access_token` is configured, else the in-memory
    `FakePatientGateway` — same conditional pattern as
    `get_specialty_gateway` below. Callers only depend on the
    `PatientGateway` Protocol.
    """
    if get_settings().dentalink_access_token:
        return _get_real_patient_gateway()
    return _get_fake_patient_gateway()


@lru_cache
def _get_fake_ycloud_messaging_gateway() -> FakeYCloudMessagingGateway:
    return FakeYCloudMessagingGateway()


@lru_cache
def _get_ycloud_client() -> YCloudClient:
    settings = get_settings()
    return YCloudClient(
        base_url=settings.ycloud_api_url,
        api_key=settings.ycloud_api_key,
        whatsapp_number=settings.ycloud_whatsapp_number,
    )


@lru_cache
def _get_real_ycloud_messaging_gateway() -> YCloudMessagingGateway:
    return YCloudMessagingGateway(_get_ycloud_client())


def get_messaging_gateway() -> MessagingGateway:
    """FastAPI dependency providing the `MessagingGateway` port.

    Returns the real, `httpx`-based `YCloudMessagingGateway` whenever
    `settings.ycloud_api_key` is configured, else the in-memory
    `FakeYCloudMessagingGateway` (e.g. local dev with no YCloud credentials)
    — callers only depend on the `MessagingGateway` Protocol.
    """
    if get_settings().ycloud_api_key:
        return _get_real_ycloud_messaging_gateway()
    return _get_fake_ycloud_messaging_gateway()


@lru_cache
def _get_fake_ycloud_handoff_gateway() -> FakeYCloudHandoffGateway:
    return FakeYCloudHandoffGateway()


@lru_cache
def _get_real_ycloud_handoff_gateway() -> YCloudHandoffGateway:
    return YCloudHandoffGateway(_get_ycloud_client())


def get_human_handoff_gateway() -> HumanHandoffGateway:
    """FastAPI dependency providing the `HumanHandoffGateway` port.

    Returns the real, `httpx`-based `YCloudHandoffGateway` whenever
    `settings.ycloud_api_key` is configured, else the in-memory
    `FakeYCloudHandoffGateway` — same conditional pattern as
    `get_messaging_gateway` below. Callers only depend on the
    `HumanHandoffGateway` Protocol.
    """
    if get_settings().ycloud_api_key:
        return _get_real_ycloud_handoff_gateway()
    return _get_fake_ycloud_handoff_gateway()


@lru_cache
def _get_fake_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


@lru_cache
def _get_llm_client() -> OpenAICompatibleLLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        settings.llm_api_url, settings.llm_api_key, settings.llm_timeout_seconds
    )


@lru_cache
def _get_real_llm_provider() -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(_get_llm_client(), get_settings().openai_model)


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency providing the `LLMProvider` port.

    Returns the real, `httpx`-based `OpenAICompatibleLLMProvider` whenever
    `settings.llm_api_url` is configured (a self-hosted 9Router instance,
    OpenAI-compatible), else the in-memory `FakeLLMProvider` — callers
    only depend on the `LLMProvider` Protocol.
    """
    if get_settings().llm_api_url:
        return _get_real_llm_provider()
    return _get_fake_llm_provider()


@lru_cache
def _get_fake_transcription_gateway() -> FakeTranscriptionGateway:
    return FakeTranscriptionGateway()


def get_transcription_gateway() -> TranscriptionGateway:
    """FastAPI dependency providing the `TranscriptionGateway` port.

    Returns the in-memory `FakeTranscriptionGateway` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.transcription.groq_transcription_gateway.GroqTranscriptionGateway`
    adapter (already implemented, not yet wired here — no live Groq
    credentials in dev this change) — callers only depend on the
    `TranscriptionGateway` Protocol.
    """
    return _get_fake_transcription_gateway()


@lru_cache
def _get_fake_media_gateway() -> FakeYCloudMediaGateway:
    return FakeYCloudMediaGateway()


def get_media_gateway() -> MediaGateway:
    """FastAPI dependency providing the `MediaGateway` port.

    Returns the in-memory `FakeYCloudMediaGateway` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.ycloud.media_gateway.YCloudMediaGateway` adapter
    (already implemented, not yet wired here — no live YCloud credentials
    in dev this change) — callers only depend on the `MediaGateway`
    Protocol.
    """
    return _get_fake_media_gateway()


@lru_cache
def _get_fake_media_downloader() -> FakeMediaDownloader:
    return FakeMediaDownloader()


def get_media_downloader() -> MediaDownloader:
    """FastAPI dependency providing the `MediaDownloader` port.

    Returns the in-memory `FakeMediaDownloader` for now. This is the swap
    point for the real, SSRF-safe
    `app.infrastructure.media.secure_media_downloader.SecureMediaDownloader`
    adapter (already implemented, not yet wired here) — callers only depend
    on the `MediaDownloader` Protocol.
    """
    return _get_fake_media_downloader()


@lru_cache
def _get_fake_telegram_notifier() -> FakeTelegramAlertNotifier:
    return FakeTelegramAlertNotifier()


def get_telegram_notifier() -> AlertNotifier:
    """FastAPI dependency providing the `AlertNotifier` port.

    Returns the in-memory `FakeTelegramAlertNotifier` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.telegram.telegram_alert_notifier.TelegramAlertNotifier`
    adapter (already implemented, not yet wired here — no live Telegram bot
    credentials in dev this change) — callers only depend on the
    `AlertNotifier` Protocol.
    """
    return _get_fake_telegram_notifier()


@lru_cache
def _get_fake_linear_gateway() -> FakeLinearIncidentGateway:
    return FakeLinearIncidentGateway()


def get_linear_gateway() -> IncidentGateway:
    """FastAPI dependency providing the `IncidentGateway` port.

    Returns the in-memory `FakeLinearIncidentGateway` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.linear.linear_incident_gateway.LinearIncidentGateway`
    adapter (already implemented, not yet wired here — no live Linear
    credentials in dev this change) — callers only depend on the
    `IncidentGateway` Protocol.
    """
    return _get_fake_linear_gateway()


@lru_cache
def _get_langgraph_agent_invoker() -> LangGraphAgentInvoker:
    return LangGraphAgentInvoker(
        appointment_gateway=get_appointment_gateway(),
        agreement_gateway=get_agreement_gateway(),
        specialty_gateway=get_specialty_gateway(),
        handoff_gateway=get_human_handoff_gateway(),
        llm_provider=get_llm_provider(),
        repositories_provider=open_sqlalchemy_agent_repositories,
        send_reply=SendReplyUseCase(get_messaging_gateway()),
        patient_gateway=get_patient_gateway(),
        proposal_repositories_provider=open_sqlalchemy_proposal_repositories,
        redis_client=get_shared_redis_client(),
        confirmation_timeout_seconds=get_settings().appointment_confirmation_timeout_seconds,
        trace_repositories_provider=open_sqlalchemy_trace_repositories,
        prompt_version=get_settings().prompt_version,
        model=get_settings().openai_model,
        alert_threshold_count=get_settings().alert_timeout_threshold_count,
        alert_window_seconds=get_settings().alert_timeout_threshold_window_seconds,
        telegram_notifier=get_telegram_notifier(),
        linear_gateway=get_linear_gateway(),
        incident_threshold_count=get_settings().incident_threshold_count,
        incident_threshold_window_seconds=get_settings().incident_threshold_window_seconds,
        telegram_alert_cooldown_seconds=get_settings().telegram_alert_cooldown_seconds,
        checkpointer_provider=get_agent_checkpointer,
    )


def get_agent_invoker() -> AgentInvoker:
    """FastAPI dependency providing the `AgentInvoker` port (Etapa 5 seam).

    Returns a real `LangGraphAgentInvoker`, wired to this module's other
    `get_*` gateways — `AppointmentGateway`/`AgreementGateway`/
    `HumanHandoffGateway`/`LLMProvider` are all still Fakes today (see each
    one's own docstring for its real-adapter swap point) — plus the real,
    Postgres-backed conversation/contact repositories and the real,
    lazily-opened Postgres checkpointer
    (`app.api.dependencies.checkpointer.get_agent_checkpointer`), needed by
    the multi-turn appointment-creation flow.
    """
    return _get_langgraph_agent_invoker()
