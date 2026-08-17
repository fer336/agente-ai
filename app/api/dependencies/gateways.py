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


@lru_cache
def _get_fake_dentalink_gateway() -> FakeDentalinkGateway:
    return FakeDentalinkGateway()


def get_appointment_gateway() -> AppointmentGateway:
    """FastAPI dependency providing the `AppointmentGateway` port.

    Returns the in-memory `FakeDentalinkGateway` for now. This is the swap
    point for the real, `httpx`-based
    `app.infrastructure.dentalink.appointment_gateway.DentalinkAppointmentGateway`
    adapter (already implemented, not yet wired here — no live Dentalink
    credentials in dev this change) — callers only depend on the
    `AppointmentGateway` Protocol.
    """
    return _get_fake_dentalink_gateway()


@lru_cache
def _get_fake_agreement_gateway() -> FakeAgreementGateway:
    return FakeAgreementGateway()


def get_agreement_gateway() -> AgreementGateway:
    """FastAPI dependency providing the `AgreementGateway` port.

    Returns the in-memory `FakeAgreementGateway` for now. This is the swap
    point for the real, `httpx`-based
    `app.infrastructure.dentalink.agreement_gateway.DentalinkAgreementGateway`
    adapter (already implemented, not yet wired here — no live Dentalink
    credentials in dev this change) — callers only depend on the
    `AgreementGateway` Protocol.
    """
    return _get_fake_agreement_gateway()


@lru_cache
def _get_fake_patient_gateway() -> FakePatientGateway:
    return FakePatientGateway()


def get_patient_gateway() -> PatientGateway:
    """FastAPI dependency providing the `PatientGateway` port.

    Returns the in-memory `FakePatientGateway` for now. This is the swap
    point for a real Dentalink-backed adapter (PRD.md §27.1's
    `GET /v1/pacientes`, not yet built — this change only wires the port
    and its Fake) — callers only depend on the `PatientGateway` Protocol.
    """
    return _get_fake_patient_gateway()


@lru_cache
def _get_fake_ycloud_messaging_gateway() -> FakeYCloudMessagingGateway:
    return FakeYCloudMessagingGateway()


def get_messaging_gateway() -> MessagingGateway:
    """FastAPI dependency providing the `MessagingGateway` port.

    Returns the in-memory `FakeYCloudMessagingGateway` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.ycloud.messaging_gateway.YCloudMessagingGateway`
    adapter (already implemented, not yet wired here — no live YCloud
    credentials in dev this change) — callers only depend on the
    `MessagingGateway` Protocol.
    """
    return _get_fake_ycloud_messaging_gateway()


@lru_cache
def _get_fake_ycloud_handoff_gateway() -> FakeYCloudHandoffGateway:
    return FakeYCloudHandoffGateway()


def get_human_handoff_gateway() -> HumanHandoffGateway:
    """FastAPI dependency providing the `HumanHandoffGateway` port.

    Returns the in-memory `FakeYCloudHandoffGateway` for now. This is the
    swap point for the real, `httpx`-based
    `app.infrastructure.ycloud.handoff_gateway.YCloudHandoffGateway` adapter
    (already implemented, not yet wired here — no live YCloud credentials in
    dev this change) — callers only depend on the `HumanHandoffGateway`
    Protocol.
    """
    return _get_fake_ycloud_handoff_gateway()


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


@lru_cache
def _get_langgraph_agent_invoker() -> LangGraphAgentInvoker:
    return LangGraphAgentInvoker(
        appointment_gateway=get_appointment_gateway(),
        agreement_gateway=get_agreement_gateway(),
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
