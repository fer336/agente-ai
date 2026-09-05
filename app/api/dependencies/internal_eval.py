from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException, status
from langgraph.checkpoint.memory import MemorySaver

from app.api.dependencies.redis import get_shared_redis_client
from app.application.admin.evaluate_chat_turn import EvaluateChatTurnUseCase
from app.application.appointments.propose_appointment import ProposalRepositories
from app.application.messages.send_reply import SendReplyUseCase
from app.application.observability.trace_repositories import TraceRepositories
from app.config.settings import Settings, get_settings
from app.infrastructure.agent.langgraph_agent_invoker import (
    AgentRepositories,
    LangGraphAgentInvoker,
)
from app.infrastructure.database.fake_agent_run_repository import FakeAgentRunRepository
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_error_repository import FakeErrorRepository
from app.infrastructure.database.fake_incident_repository import FakeIncidentRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.database.fake_node_execution_repository import FakeNodeExecutionRepository
from app.infrastructure.database.fake_outbox_repository import FakeOutboxRepository
from app.infrastructure.database.fake_pending_action_repository import (
    FakePendingActionRepository,
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
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway


def require_internal_eval_enabled(settings: Settings = Depends(get_settings)) -> None:
    """Raises a generic 404 when `internal_eval_enabled` is off (PRD.md
    §74.3: disabled by default in production). Declared as its own,
    auth-independent dependency — and listed BEFORE `require_role` in the
    route's signature — so a disabled endpoint responds identically to a
    nonexistent one even for an unauthenticated caller, instead of leaking
    "this route exists, you're just unauthorized" via a 401.
    """
    if not settings.internal_eval_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def get_evaluate_chat_turn_use_case() -> EvaluateChatTurnUseCase:
    """Builds one fully isolated `EvaluateChatTurnUseCase` per request (PRD.md
    §61) — every repository, gateway, and the `LangGraphAgentInvoker` itself
    are freshly constructed here, never shared with the production
    `app.api.dependencies.gateways.get_agent_invoker()` singleton and never
    `@lru_cache`d: two concurrent eval calls (or two Promptfoo test cases)
    must never see each other's state, and this endpoint must never touch
    the real Dentalink/YCloud/Groq adapters regardless of how production DI
    evolves once Etapa 11/12 wire those in for real (PRD.md §61's own
    diagram: "Promptfoo → FastAPI → LangGraph → FakeDentalinkGateway →
    FakeYCloudGateway").

    Redis and the LangGraph checkpointer are the two exceptions: the real
    shared Redis client is reused (it holds only locks/debounce counters/
    rate-limit counts keyed by a synthetic eval `conversation_id`, never
    patient data), and `MemorySaver` (an in-process, real `langgraph`
    checkpointer — not a test fixture) replaces the production Postgres
    checkpointer so this endpoint needs no database at all.
    """
    conversations = FakeConversationRepository()
    contacts = FakeContactRepository()
    messages = FakeMessageRepository()
    contact_memories = FakeContactMemoryRepository()
    agent_runs = FakeAgentRunRepository()
    node_executions = FakeNodeExecutionRepository()
    tool_executions = FakeToolExecutionRepository()
    errors = FakeErrorRepository()
    incidents = FakeIncidentRepository()
    pending_actions = FakePendingActionRepository()
    scheduled_actions = FakeScheduledActionRepository()
    outbox = FakeOutboxRepository()
    messaging_gateway = FakeYCloudMessagingGateway()

    @asynccontextmanager
    async def agent_repositories_provider() -> AsyncIterator[AgentRepositories]:
        yield AgentRepositories(
            conversations=conversations,
            contacts=contacts,
            messages=messages,
            contact_memories=contact_memories,
        )

    @asynccontextmanager
    async def trace_repositories_provider() -> AsyncIterator[TraceRepositories]:
        yield TraceRepositories(
            agent_runs=agent_runs,
            node_executions=node_executions,
            tool_executions=tool_executions,
            errors=errors,
            incidents=incidents,
        )

    @asynccontextmanager
    async def proposal_repositories_provider() -> AsyncIterator[ProposalRepositories]:
        yield ProposalRepositories(
            pending_actions=pending_actions,
            scheduled_actions=scheduled_actions,
            outbox=outbox,
        )

    async def checkpointer_provider() -> MemorySaver:
        return MemorySaver()

    settings = get_settings()
    agent_invoker = LangGraphAgentInvoker(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=FakeAgreementGateway(),
        specialty_gateway=FakeSpecialtyGateway(),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        repositories_provider=agent_repositories_provider,
        send_reply=SendReplyUseCase(messaging_gateway),
        patient_gateway=FakePatientGateway(),
        proposal_repositories_provider=proposal_repositories_provider,
        memory_recent_window_size=settings.memory_recent_window_size,
        redis_client=get_shared_redis_client(),
        confirmation_timeout_seconds=settings.appointment_confirmation_timeout_seconds,
        trace_repositories_provider=trace_repositories_provider,
        prompt_version=settings.prompt_version,
        model=settings.openai_model,
        alert_threshold_count=settings.alert_timeout_threshold_count,
        alert_window_seconds=settings.alert_timeout_threshold_window_seconds,
        telegram_notifier=FakeTelegramAlertNotifier(),
        linear_gateway=FakeLinearIncidentGateway(),
        incident_threshold_count=settings.incident_threshold_count,
        incident_threshold_window_seconds=settings.incident_threshold_window_seconds,
        telegram_alert_cooldown_seconds=settings.telegram_alert_cooldown_seconds,
        checkpointer_provider=checkpointer_provider,
    )

    return EvaluateChatTurnUseCase(
        conversations=conversations,
        contacts=contacts,
        messages=messages,
        agent_runs=agent_runs,
        node_executions=node_executions,
        tool_executions=tool_executions,
        agent_invoker=agent_invoker,
        messaging_gateway=messaging_gateway,
    )
