from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from redis.asyncio import Redis

from app.agent.graph import compile_graph
from app.agent.state import AgentState
from app.application.appointments.propose_appointment import ProposalRepositoriesProvider
from app.application.errors.error_service import ErrorService
from app.application.memory.memory_service import MemoryService
from app.application.messages.send_reply import SendReplyUseCase
from app.application.observability.trace_repositories import TraceRepositoriesProvider
from app.domain.entities.agent_run import COMPLETED, FAILED, HANDOFF, RUNNING, AgentRun
from app.domain.entities.node_execution import FAILED as NODE_EXECUTION_FAILED
from app.domain.entities.node_execution import NodeExecution
from app.domain.repositories.alert_notifier import AlertNotifier
from app.domain.repositories.contact_memory_repository import ContactMemoryRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    PatientGateway,
    SpecialtyGateway,
)
from app.domain.repositories.incident_gateway import IncidentGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.conversation_id import ConversationId


@dataclass(frozen=True)
class AgentRepositories:
    """Bundles the repositories one `LangGraphAgentInvoker.handle()` call needs."""

    conversations: ConversationRepository
    contacts: ContactRepository
    #: Conversational-memory module's session-scoped repos (no PRD.md
    #: section number — this session's own brief) — `MemoryService` is
    #: built fresh per `handle()` call from these, same "no eager I/O,
    #: session bound per call" reasoning as `conversations`/`contacts`
    #: above (see this class's own docstring in `open_sqlalchemy_agent_repositories`).
    messages: MessageRepository
    contact_memories: ContactMemoryRepository


RepositoriesProvider = Callable[[], AbstractAsyncContextManager[AgentRepositories]]
CheckpointerProvider = Callable[[], Awaitable["BaseCheckpointSaver[Any]"]]


class LangGraphAgentInvoker:
    """Real `AgentInvoker` (Etapa 5 seam) — builds and runs the LangGraph
    agent, then sends its reply.

    Mirrors `IngestMessageUseCase`'s own `repositories_provider` pattern
    (see its docstring for the full rationale): this invoker is a
    process-level singleton (built once by
    `app.api.dependencies.gateways.get_agent_invoker`), but
    `ConversationRepository`/`ContactRepository`'s only production
    implementation is session-bound — a session must NOT be held open for
    the app's whole lifetime. `repositories_provider` opens a FRESH session
    for every `handle()` call instead.

    `checkpointer_provider` is a callable (not a `BaseCheckpointSaver`
    instance) for the same "no eager I/O at DI-wiring time" reason:
    `AsyncPostgresSaver`'s underlying connection pool needs an `await
    pool.open()` before use, which cannot happen inside the synchronous
    `@lru_cache`d function that builds this invoker
    (`app.api.dependencies.gateways._get_langgraph_agent_invoker`). The
    default provider (`app.api.dependencies.checkpointer.get_agent_checkpointer`)
    lazily opens the pool on the FIRST `handle()` call that needs it and
    caches the result itself, so calling it here on every `handle()` is
    cheap after that. `None` (the default) disables checkpointing entirely
    — fine for single-turn flows (agreement/handoff/fallback), required
    for multi-turn ones (appointment creation).

    The graph is recompiled on every call for the same reason:
    `check_conversation_mode`/`handoff` nodes close over the session-bound
    `ConversationRepository` at build time, so a graph built once at
    startup would keep reusing a long-closed session. Recompiling is cheap
    (pure node/edge wiring, no I/O) — the checkpointer (when configured,
    keyed by `thread_id`) is what actually carries state across calls, not
    the Python graph object itself.

    Multi-turn carry-over is explicit, not implicit: `handle()` reads the
    thread's last checkpointed `collected_data`/`missing_fields`/
    `pending_action_id`/`appointment_action` (when a checkpointer is
    configured) and seeds THIS turn's initial state from them, while
    `user_message`/`button_payload`/`intent`/`response_text`/`error`/
    `requires_handoff` always start fresh — those are per-turn-only
    signals, never carried memory. Relying on LangGraph's own implicit
    partial-input-merge behavior here would be one more thing to get
    subtly wrong in the codebase's most safety-critical flow (PRD.md §72).

    Traceability (PRD.md §38-39): every `handle()` call creates one
    `AgentRun` — written once as `running` before the graph invokes, once
    more with its terminal `status` after. `trace_repositories_provider`
    is a SEPARATE provider from `repositories_provider` (its own session,
    explicit commit) — see `app.api.dependencies.repositories.
    open_sqlalchemy_trace_repositories`'s own docstring for why tracing
    durability is handled independently of the conversational repositories.
    """

    def __init__(
        self,
        appointment_gateway: AppointmentGateway,
        agreement_gateway: AgreementGateway,
        specialty_gateway: SpecialtyGateway,
        handoff_gateway: HumanHandoffGateway,
        llm_provider: LLMProvider,
        repositories_provider: RepositoriesProvider,
        send_reply: SendReplyUseCase,
        patient_gateway: PatientGateway,
        proposal_repositories_provider: ProposalRepositoriesProvider,
        memory_recent_window_size: int,
        redis_client: Redis,
        confirmation_timeout_seconds: int,
        trace_repositories_provider: TraceRepositoriesProvider,
        prompt_version: str,
        model: str,
        alert_threshold_count: int,
        alert_window_seconds: int,
        telegram_notifier: AlertNotifier,
        linear_gateway: IncidentGateway,
        incident_threshold_count: int,
        incident_threshold_window_seconds: int,
        telegram_alert_cooldown_seconds: int,
        checkpointer_provider: CheckpointerProvider | None = None,
    ) -> None:
        self._appointment_gateway = appointment_gateway
        self._agreement_gateway = agreement_gateway
        self._specialty_gateway = specialty_gateway
        self._handoff_gateway = handoff_gateway
        self._llm_provider = llm_provider
        self._repositories_provider = repositories_provider
        self._send_reply = send_reply
        self._patient_gateway = patient_gateway
        self._proposal_repositories_provider = proposal_repositories_provider
        self._memory_recent_window_size = memory_recent_window_size
        self._redis_client = redis_client
        self._confirmation_timeout_seconds = confirmation_timeout_seconds
        self._trace_repositories_provider = trace_repositories_provider
        self._prompt_version = prompt_version
        self._model = model
        self._alert_threshold_count = alert_threshold_count
        self._alert_window_seconds = alert_window_seconds
        self._telegram_notifier = telegram_notifier
        self._linear_gateway = linear_gateway
        self._incident_threshold_count = incident_threshold_count
        self._incident_threshold_window_seconds = incident_threshold_window_seconds
        self._telegram_alert_cooldown_seconds = telegram_alert_cooldown_seconds
        self._checkpointer_provider = checkpointer_provider

    async def handle(
        self,
        conversation_id: ConversationId,
        message_ids: list[str],
        user_message: str,
        button_payload: str | None,
    ) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": str(conversation_id)}}
        checkpointer = (
            await self._checkpointer_provider()
            if self._checkpointer_provider is not None
            else None
        )

        agent_run_id = str(uuid4())
        trace_id = str(uuid4())
        started_at = datetime.now(UTC)
        # PRD.md §39's `agent_runs.message_id` is singular; a debounced turn
        # can carry several grouped `message_ids` (`IngestMessageUseCase`)
        # — the LAST one is the representative trigger, same "last wins"
        # precedent already used for `button_payload` in that same grouping
        # step.
        message_id = message_ids[-1]

        async with self._trace_repositories_provider() as trace_repositories:
            error_service = ErrorService(
                trace_repositories.errors,
                trace_repositories.incidents,
                self._telegram_notifier,
                self._linear_gateway,
                alert_threshold_count=self._alert_threshold_count,
                alert_window_seconds=self._alert_window_seconds,
                incident_threshold_count=self._incident_threshold_count,
                incident_threshold_window_seconds=self._incident_threshold_window_seconds,
                telegram_alert_cooldown_seconds=self._telegram_alert_cooldown_seconds,
            )
            await trace_repositories.agent_runs.save(
                AgentRun(
                    id=agent_run_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    trace_id=trace_id,
                    prompt_version=self._prompt_version,
                    model=self._model,
                    started_at=started_at,
                    finished_at=None,
                    status=RUNNING,
                    current_node=None,
                    error_id=None,
                )
            )

            async with self._repositories_provider() as repositories:
                compiled_graph = compile_graph(
                    self._appointment_gateway,
                    self._agreement_gateway,
                    self._specialty_gateway,
                    self._handoff_gateway,
                    self._llm_provider,
                    repositories.conversations,
                    self._patient_gateway,
                    self._proposal_repositories_provider,
                    self._redis_client,
                    self._confirmation_timeout_seconds,
                    trace_repositories.node_executions,
                    agent_run_id,
                    trace_repositories.tool_executions,
                    error_service,
                    checkpointer=checkpointer,
                )

                previous_values: dict[str, Any] = {}
                if checkpointer is not None:
                    snapshot = await compiled_graph.aget_state(config)
                    previous_values = snapshot.values or {}

                recent_messages: list[dict[str, str]] = []
                contact_memory_summary: str | None = None
                conversation_for_memory = await repositories.conversations.get_by_id(
                    conversation_id
                )
                if conversation_for_memory is not None:
                    contact_for_memory = await repositories.contacts.get_by_id(
                        conversation_for_memory.contact_id
                    )
                    if contact_for_memory is not None:
                        memory_service = MemoryService(
                            contact_memory_repository=repositories.contact_memories,
                            message_repository=repositories.messages,
                            llm_provider=self._llm_provider,
                            recent_window_size=self._memory_recent_window_size,
                            redis_client=self._redis_client,
                        )
                        (
                            recent_messages,
                            contact_memory_summary,
                        ) = await memory_service.build_agent_context(
                            conversation_id, contact_for_memory.id
                        )

                initial_state: AgentState = {
                    "conversation_id": str(conversation_id),
                    "message_ids": message_ids,
                    "user_message": user_message,
                    "button_payload": button_payload,
                    "recent_messages": recent_messages,
                    "contact_memory_summary": contact_memory_summary,
                    "intent": None,
                    "appointment_action": previous_values.get("appointment_action"),
                    "collected_data": previous_values.get("collected_data", {}),
                    "missing_fields": previous_values.get("missing_fields", []),
                    "pending_action_id": previous_values.get("pending_action_id"),
                    "response_text": None,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "error": None,
                }
                result = await compiled_graph.ainvoke(initial_state, config=config)

                node_executions = await trace_repositories.node_executions.get_by_agent_run_id(
                    agent_run_id
                )
                await trace_repositories.agent_runs.save(
                    AgentRun(
                        id=agent_run_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        trace_id=trace_id,
                        prompt_version=self._prompt_version,
                        model=self._model,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        status=_final_status(node_executions, result),
                        current_node=node_executions[-1].node_name if node_executions else None,
                        error_id=None,
                    )
                )

                response_text = result.get("response_text")
                if not response_text:
                    # Either the conversation is already in HUMAN mode (graph
                    # ends silently, PRD.md §21) or a node genuinely produced
                    # no reply — both are valid "say nothing" outcomes.
                    return
                response_buttons = result.get("response_buttons")

                conversation = await repositories.conversations.get_by_id(conversation_id)
                if conversation is None:
                    return
                contact = await repositories.contacts.get_by_id(conversation.contact_id)
                if contact is None:
                    return
                phone = contact.phone

        await self._send_reply.execute(phone, response_text, response_buttons)


def _final_status(node_executions: list[NodeExecution], result: dict[str, object]) -> str:
    """Derives the `AgentRun.status` PRD.md §39 wants (running/completed/failed/handoff).

    `result["error"]` is unreliable for this — `handle_error_node` clears
    it back to `None` on its way out (see that node's own docstring) so it
    never leaks into the next turn's checkpointed state. Whether THIS run
    failed is instead read back from the `NodeExecution` rows it just
    wrote: if any node failed, `with_error_handling` already routed to
    `handle_error`, so the run is `failed` regardless of the safe fallback
    reply `handle_error_node` produced.
    """
    if any(node_execution.status == NODE_EXECUTION_FAILED for node_execution in node_executions):
        return FAILED
    if result.get("requires_handoff"):
        return HANDOFF
    return COMPLETED
