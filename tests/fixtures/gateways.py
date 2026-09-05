"""Shared fake-gateway factory functions for tests.

Plain factory functions (not `@pytest.fixture`s) — fakes have no
setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline `Fake*()` construction these replace.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.application.appointments.propose_appointment import ProposalRepositories
from app.application.config.runtime_config_service import RuntimeConfigService
from app.application.errors.error_service import ErrorService
from app.application.memory.memory_service import MemoryService
from app.application.messages.ingest_message import IngestMessageUseCase, MessageRepositories
from app.application.messages.send_reply import SendReplyUseCase
from app.application.observability.trace_repositories import TraceRepositories
from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.domain.entities.specialty import Specialty
from app.infrastructure.agent.fake_agent_invoker import FakeAgentInvoker
from app.infrastructure.database.fake_agent_run_repository import FakeAgentRunRepository
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_error_repository import FakeErrorRepository
from app.infrastructure.database.fake_incident_repository import FakeIncidentRepository
from app.infrastructure.database.fake_media_processing_job_repository import (
    FakeMediaProcessingJobRepository,
)
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.database.fake_node_execution_repository import (
    FakeNodeExecutionRepository,
)
from app.infrastructure.database.fake_outbox_repository import FakeOutboxRepository
from app.infrastructure.database.fake_pending_action_repository import (
    FakePendingActionRepository,
)
from app.infrastructure.database.fake_runtime_config_repository import (
    FakeRuntimeConfigRepository,
)
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from app.infrastructure.database.fake_tool_execution_repository import (
    FakeToolExecutionRepository,
)
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway
from app.infrastructure.linear.fake_linear_incident_gateway import FakeLinearIncidentGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.redis.debounce import DebounceTracker
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.fake_redis import InMemoryFakeRedis


def make_dentalink_gateway(
    available_slots: list[AppointmentSlot] | None = None,
    professionals: list[Professional] | None = None,
) -> FakeDentalinkGateway:
    return FakeDentalinkGateway(available_slots=available_slots, professionals=professionals)


def make_agreement_gateway(
    agreements: list[Agreement] | None = None,
    patient_agreements: dict[str, list[Agreement]] | None = None,
) -> FakeAgreementGateway:
    return FakeAgreementGateway(agreements=agreements, patient_agreements=patient_agreements)


def make_specialty_gateway(specialties: list[Specialty] | None = None) -> FakeSpecialtyGateway:
    return FakeSpecialtyGateway(specialties=specialties)


def make_patient_gateway(patients: list[Patient] | None = None) -> FakePatientGateway:
    return FakePatientGateway(patients=patients)


def make_ycloud_handoff_gateway() -> FakeYCloudHandoffGateway:
    return FakeYCloudHandoffGateway()


def make_ycloud_messaging_gateway() -> FakeYCloudMessagingGateway:
    return FakeYCloudMessagingGateway()


def make_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


def make_contact_repository() -> FakeContactRepository:
    return FakeContactRepository()


def make_message_repository() -> FakeMessageRepository:
    return FakeMessageRepository()


def make_contact_memory_repository() -> FakeContactMemoryRepository:
    return FakeContactMemoryRepository()


def make_memory_service(
    message_repository: FakeMessageRepository | None = None,
    contact_memory_repository: FakeContactMemoryRepository | None = None,
    llm_provider: FakeLLMProvider | None = None,
    recent_window_size: int = 15,
    redis_client: InMemoryFakeRedis | None = None,
) -> MemoryService:
    return MemoryService(
        contact_memory_repository=contact_memory_repository or make_contact_memory_repository(),
        message_repository=message_repository or make_message_repository(),
        llm_provider=llm_provider or make_llm_provider(),
        recent_window_size=recent_window_size,
        redis_client=redis_client,
    )


def make_media_processing_job_repository() -> FakeMediaProcessingJobRepository:
    return FakeMediaProcessingJobRepository()


def make_conversation_repository() -> FakeConversationRepository:
    return FakeConversationRepository()


def make_pending_action_repository() -> FakePendingActionRepository:
    return FakePendingActionRepository()


def make_scheduled_action_repository() -> FakeScheduledActionRepository:
    return FakeScheduledActionRepository()


def make_outbox_repository() -> FakeOutboxRepository:
    return FakeOutboxRepository()


def make_agent_run_repository() -> FakeAgentRunRepository:
    return FakeAgentRunRepository()


def make_node_execution_repository() -> FakeNodeExecutionRepository:
    return FakeNodeExecutionRepository()


def make_tool_execution_repository() -> FakeToolExecutionRepository:
    return FakeToolExecutionRepository()


def make_error_repository() -> FakeErrorRepository:
    return FakeErrorRepository()


def make_incident_repository() -> FakeIncidentRepository:
    return FakeIncidentRepository()


def make_telegram_notifier() -> FakeTelegramAlertNotifier:
    return FakeTelegramAlertNotifier()


def make_linear_gateway() -> FakeLinearIncidentGateway:
    return FakeLinearIncidentGateway()


def make_error_service(
    error_repository: FakeErrorRepository | None = None,
    alert_threshold_count: int = 5,
    alert_window_seconds: int = 120,
    incident_repository: FakeIncidentRepository | None = None,
    telegram_notifier: FakeTelegramAlertNotifier | None = None,
    linear_gateway: FakeLinearIncidentGateway | None = None,
    incident_threshold_count: int = 10,
    incident_threshold_window_seconds: int = 300,
    telegram_alert_cooldown_seconds: int = 900,
) -> ErrorService:
    return ErrorService(
        error_repository if error_repository is not None else make_error_repository(),
        incident_repository if incident_repository is not None else make_incident_repository(),
        telegram_notifier if telegram_notifier is not None else make_telegram_notifier(),
        linear_gateway if linear_gateway is not None else make_linear_gateway(),
        alert_threshold_count=alert_threshold_count,
        alert_window_seconds=alert_window_seconds,
        incident_threshold_count=incident_threshold_count,
        incident_threshold_window_seconds=incident_threshold_window_seconds,
        telegram_alert_cooldown_seconds=telegram_alert_cooldown_seconds,
    )


def make_trace_repositories_provider(
    agent_runs: FakeAgentRunRepository | None = None,
    node_executions: FakeNodeExecutionRepository | None = None,
    tool_executions: FakeToolExecutionRepository | None = None,
    errors: FakeErrorRepository | None = None,
    incidents: FakeIncidentRepository | None = None,
):
    """Builds a `TraceRepositoriesProvider` wired entirely to fakes.

    Yields the SAME repository instances on every call, matching
    `make_proposal_repositories_provider`'s own rationale — a graph run's
    node executions and its `AgentRun` must all be visible to each other
    within the same `handle()` call.
    """
    agent_runs = agent_runs if agent_runs is not None else make_agent_run_repository()
    node_executions = (
        node_executions if node_executions is not None else make_node_execution_repository()
    )
    tool_executions = (
        tool_executions if tool_executions is not None else make_tool_execution_repository()
    )
    errors = errors if errors is not None else make_error_repository()
    incidents = incidents if incidents is not None else make_incident_repository()

    @asynccontextmanager
    async def provider() -> AsyncIterator[TraceRepositories]:
        yield TraceRepositories(
            agent_runs=agent_runs,
            node_executions=node_executions,
            tool_executions=tool_executions,
            errors=errors,
            incidents=incidents,
        )

    return provider


def make_proposal_repositories_provider(
    pending_actions: FakePendingActionRepository | None = None,
    scheduled_actions: FakeScheduledActionRepository | None = None,
    outbox: FakeOutboxRepository | None = None,
):
    """Builds a `ProposalRepositoriesProvider` wired entirely to fakes.

    Yields the SAME repository instances on every call (not fresh ones per
    call) — the appointment stage machine's propose/confirm/reject turns
    are separate `node()` invocations that must all see each other's writes,
    matching how `open_sqlalchemy_proposal_repositories` shares one
    committed session's rows across requests in production.
    """
    pending_actions = (
        pending_actions if pending_actions is not None else make_pending_action_repository()
    )
    scheduled_actions = (
        scheduled_actions if scheduled_actions is not None else make_scheduled_action_repository()
    )
    outbox = outbox if outbox is not None else make_outbox_repository()

    @asynccontextmanager
    async def provider() -> AsyncIterator[ProposalRepositories]:
        yield ProposalRepositories(
            pending_actions=pending_actions,
            scheduled_actions=scheduled_actions,
            outbox=outbox,
        )

    return provider


def make_agent_invoker() -> FakeAgentInvoker:
    return FakeAgentInvoker()


def make_send_reply_use_case(
    messaging_gateway: FakeYCloudMessagingGateway | None = None,
) -> SendReplyUseCase:
    messaging_gateway = (
        messaging_gateway if messaging_gateway is not None else make_ycloud_messaging_gateway()
    )
    return SendReplyUseCase(messaging_gateway)


def make_runtime_config_service(
    debounce_seconds: float = 6,
    model: str = "fake-model",
    temperature: float = 0.0,
    classify_intent_prompt: str = "classify this",
    extract_information_prompt: str = "extract {required_fields}",
    generate_response_prompt: str = "respond to {intent} with {collected_data}",
    repository: FakeRuntimeConfigRepository | None = None,
) -> RuntimeConfigService:
    """Builds a `RuntimeConfigService` wired to a `FakeRuntimeConfigRepository`
    (no Redis — every `get_config()` reads the fake directly, deterministic
    for tests). `debounce_seconds` is deliberately `float` here (not the
    domain entity's `int`) — several existing tests set it to a fraction of
    a second (e.g. `0.05`) to keep `IngestMessageUseCase`'s debounce-window
    test suite fast; Python doesn't enforce dataclass field types at
    runtime, so this passes through untouched.
    """
    repository = repository if repository is not None else FakeRuntimeConfigRepository()

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[FakeRuntimeConfigRepository]:
        yield repository

    def default_config() -> RuntimeAgentConfig:
        return RuntimeAgentConfig(
            id="default",
            model=model,
            temperature=temperature,
            debounce_seconds=debounce_seconds,  # type: ignore[arg-type]
            classify_intent_prompt=classify_intent_prompt,
            extract_information_prompt=extract_information_prompt,
            generate_response_prompt=generate_response_prompt,
            updated_at=datetime.now(UTC),
            updated_by="test-default",
        )

    return RuntimeConfigService(
        repositories_provider=repositories_provider,
        default_config=default_config,
        redis_client=None,
    )


def make_ingest_message_use_case(
    message_repository: FakeMessageRepository | None = None,
    contact_repository: FakeContactRepository | None = None,
    conversation_repository: FakeConversationRepository | None = None,
    media_processing_job_repository: FakeMediaProcessingJobRepository | None = None,
    redis_client: InMemoryFakeRedis | None = None,
    agent_invoker: FakeAgentInvoker | None = None,
    send_reply: SendReplyUseCase | None = None,
    debounce_seconds: float = 6,
    runtime_config_service: RuntimeConfigService | None = None,
    audio_rate_limit_per_minute: int = 0,
) -> IngestMessageUseCase:
    """Builds an `IngestMessageUseCase` wired entirely to fakes.

    Used both by `tests/unit/application/messages/test_ingest_message.py`
    and by `tests/unit/api/routes/test_webhook.py` (via
    `app.dependency_overrides[get_ingest_message_use_case]`) so route-level
    tests never construct the real, Postgres/Redis-backed production
    singleton (`app.api.dependencies.use_cases.get_ingest_message_use_case`).
    """
    message_repository = (
        message_repository if message_repository is not None else make_message_repository()
    )
    contact_repository = (
        contact_repository if contact_repository is not None else make_contact_repository()
    )
    conversation_repository = (
        conversation_repository
        if conversation_repository is not None
        else make_conversation_repository()
    )
    media_processing_job_repository = (
        media_processing_job_repository
        if media_processing_job_repository is not None
        else make_media_processing_job_repository()
    )
    redis_client = redis_client if redis_client is not None else InMemoryFakeRedis()
    agent_invoker = agent_invoker if agent_invoker is not None else make_agent_invoker()
    send_reply = send_reply if send_reply is not None else make_send_reply_use_case()
    debounce_tracker = DebounceTracker(redis_client, debounce_seconds)
    runtime_config_service = (
        runtime_config_service
        if runtime_config_service is not None
        else make_runtime_config_service(debounce_seconds=debounce_seconds)
    )

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[MessageRepositories]:
        yield MessageRepositories(
            messages=message_repository,
            contacts=contact_repository,
            conversations=conversation_repository,
            media_processing_jobs=media_processing_job_repository,
        )

    return IngestMessageUseCase(
        repositories_provider=repositories_provider,
        debounce_tracker=debounce_tracker,
        redis_client=redis_client,
        agent_invoker=agent_invoker,
        runtime_config_service=runtime_config_service,
        send_reply=send_reply,
        audio_rate_limit_per_minute=audio_rate_limit_per_minute,
    )
