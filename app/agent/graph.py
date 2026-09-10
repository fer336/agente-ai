from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from redis.asyncio import Redis

from app.agent.nodes.agreement import create_agreement_node
from app.agent.nodes.appointment import create_appointment_node
from app.agent.nodes.check_conversation_mode import create_check_conversation_mode_node
from app.agent.nodes.error_handling import with_error_handling
from app.agent.nodes.fallback import create_fallback_node
from app.agent.nodes.fresh_restart import FRESH_RESTART_STATE_KEY, fresh_restart_node
from app.agent.nodes.handle_error import handle_error_node
from app.agent.nodes.handoff import create_handoff_node
from app.agent.nodes.location import location_node
from app.agent.nodes.question import question_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.agent.nodes.specialties import create_specialties_node
from app.agent.nodes.treatment_catalog import create_treatment_catalog_node
from app.agent.state import AgentState
from app.application.appointments.propose_appointment import ProposalRepositoriesProvider
from app.application.errors.error_service import ErrorService
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    PatientGateway,
    SpecialtyGateway,
)
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

    #: Pool typed with the dict row factory `AsyncPostgresSaver` requires —
    #: matches what `create_postgres_checkpointer_pool` actually constructs.
    PostgresCheckpointerPool = AsyncConnectionPool[AsyncConnection[dict[str, Any]]]

#: Node names (PRD.md §29). `receive_message` has no node here — by the
#: time `AgentInvoker.handle()`/this graph runs, `IngestMessageUseCase`
#: (Etapa 4) has already deduped, persisted, debounced, and grouped the
#: inbound message(s) into `AgentState.user_message`; the graph starts
#: effectively at `check_conversation_mode`.
CHECK_CONVERSATION_MODE_NODE = "check_conversation_mode"
RESOLVE_INTERACTION_NODE = "resolve_interaction"
#: Deterministic clean-restart node (see `app.agent.nodes.fresh_restart`):
#: the first turn after a `/bot` reactivation or the lazy 1h timeout routes
#: straight here — skipping intent classification — and renders the
#: canonical welcome menu instead of LLM-continuing the old thread.
FRESH_RESTART_NODE = "fresh_restart"
APPOINTMENT_NODE = "appointment"
AGREEMENT_NODE = "agreement"
SPECIALTIES_NODE = "specialties"
#: Static FAQ catalog of commonly-asked treatments (this session's own
#: brief) — distinct from `SPECIALTIES_NODE`'s live Dentalink
#: specialty/booking flow, see `app.agent.nodes.treatment_catalog`'s
#: own docstring.
TREATMENT_CATALOG_NODE = "treatment_catalog"
HANDOFF_NODE = "handoff"
QUESTION_NODE = "question"
LOCATION_NODE = "location"
FALLBACK_NODE = "fallback"
HANDLE_ERROR_NODE = "handle_error"

#: Kept for the standalone tool->use-case->gateway demo node/tests
#: (`app/agent/nodes/search_availability.py`) — no longer wired into
#: `build_graph`'s production topology, superseded by `APPOINTMENT_NODE`.
SEARCH_AVAILABILITY_NODE = "search_availability"


def _route_after_mode_check(state: AgentState) -> str:
    if state.get("error"):
        return HANDLE_ERROR_NODE
    if state.get("requires_handoff") and state.get("intent") is None:
        # `check_conversation_mode` found mode == "human" and nothing else
        # ran yet — produce no reply, end the run silently (PRD.md §21:
        # "LangGraph NO responde automáticamente" while in HUMAN mode).
        return END
    if (state.get("collected_data") or {}).get(FRESH_RESTART_STATE_KEY):
        # Fresh reactivation (`/bot` or lazy 1h timeout): render the
        # canonical welcome menu deterministically — skip intent
        # classification entirely (see `fresh_restart.py`).
        return FRESH_RESTART_NODE
    return RESOLVE_INTERACTION_NODE


def _route_after_fresh_restart(state: AgentState) -> str:
    """The fresh-restart turn IS the answer (welcome + main menu): end."""
    return END


def _route_after_resolve_interaction(state: AgentState) -> str:
    if state.get("error"):
        return HANDLE_ERROR_NODE
    intent = state.get("intent")
    if intent == "appointment":
        return APPOINTMENT_NODE
    if intent == "insurance":
        return AGREEMENT_NODE
    if intent == "specialties":
        return SPECIALTIES_NODE
    if intent == "treatment_catalog":
        return TREATMENT_CATALOG_NODE
    if intent == "handoff":
        return HANDOFF_NODE
    if intent == "question":
        return QUESTION_NODE
    if intent == "location":
        return LOCATION_NODE
    return FALLBACK_NODE


def _route_after_business_node(state: AgentState) -> str:
    return HANDLE_ERROR_NODE if state.get("error") else END


def build_graph(
    appointment_gateway: AppointmentGateway,
    agreement_gateway: AgreementGateway,
    specialty_gateway: SpecialtyGateway,
    handoff_gateway: HumanHandoffGateway,
    llm_provider: LLMProvider,
    conversation_repository: ConversationRepository,
    patient_gateway: PatientGateway,
    proposal_repositories_provider: ProposalRepositoriesProvider,
    redis_client: Redis,
    confirmation_timeout_seconds: int,
    node_execution_repository: NodeExecutionRepository,
    agent_run_id: str,
    tool_execution_repository: ToolExecutionRepository,
    error_service: ErrorService,
    verification_flow_id: str = "",
    registration_flow_id: str = "",
) -> StateGraph[AgentState, None, AgentState, AgentState]:
    """Builds the (uncompiled) agent graph (PRD.md §29):

    ```
    START -> check_conversation_mode -> resolve_interaction
                                             |-- appointment
                                             |-- agreement
                                             |-- specialties
                                             |-- treatment_catalog
                                             |-- handoff
                                             |-- question
                                             |-- location
                                             `-- fallback
    (any node's exception) -> handle_error -> END
    ```

    Kept separate from `compile_graph` so tests can inspect graph structure
    (nodes/edges) without needing a checkpointer at all. Every business
    node is wrapped with `with_error_handling` (PRD.md §30) — `handle_error`
    itself is NOT wrapped, so a bug in its own safe-fallback logic surfaces
    instead of looping.

    `patient_gateway`/`proposal_repositories_provider`/`redis_client`/
    `confirmation_timeout_seconds` exist solely for `APPOINTMENT_NODE`'s
    full turno management stage machine — create/reschedule/cancel
    (PRD.md §9-16, §32) — see
    `app.agent.nodes.appointment.create_appointment_node`'s own docstring.

    `node_execution_repository`/`agent_run_id` are threaded into every
    `with_error_handling` call so each node records a `NodeExecution`
    (PRD.md §40) against the `AgentRun` `LangGraphAgentInvoker.handle()`
    already created for this turn. `tool_execution_repository` rides along
    so `with_error_handling` can open each node's `TraceContext` (PRD.md
    §41) — see that function's own docstring.
    """
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    graph.add_node(
        CHECK_CONVERSATION_MODE_NODE,
        with_error_handling(
            CHECK_CONVERSATION_MODE_NODE,
            create_check_conversation_mode_node(conversation_repository),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        RESOLVE_INTERACTION_NODE,
        with_error_handling(
            RESOLVE_INTERACTION_NODE,
            create_resolve_interaction_node(llm_provider),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        FRESH_RESTART_NODE,
        with_error_handling(
            FRESH_RESTART_NODE,
            fresh_restart_node,
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        APPOINTMENT_NODE,
        with_error_handling(
            APPOINTMENT_NODE,
            create_appointment_node(
                appointment_gateway,
                patient_gateway,
                proposal_repositories_provider,
                conversation_repository,
                redis_client,
                confirmation_timeout_seconds,
                llm_provider,
                specialty_gateway,
                agreement_gateway,
                verification_flow_id,
                registration_flow_id,
            ),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        AGREEMENT_NODE,
        with_error_handling(
            AGREEMENT_NODE,
            create_agreement_node(agreement_gateway),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        SPECIALTIES_NODE,
        with_error_handling(
            SPECIALTIES_NODE,
            create_specialties_node(specialty_gateway, appointment_gateway),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        TREATMENT_CATALOG_NODE,
        with_error_handling(
            TREATMENT_CATALOG_NODE,
            create_treatment_catalog_node(),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        HANDOFF_NODE,
        with_error_handling(
            HANDOFF_NODE,
            create_handoff_node(handoff_gateway, conversation_repository),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        QUESTION_NODE,
        with_error_handling(
            QUESTION_NODE,
            question_node,
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        LOCATION_NODE,
        with_error_handling(
            LOCATION_NODE,
            location_node,
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(
        FALLBACK_NODE,
        with_error_handling(
            FALLBACK_NODE,
            create_fallback_node(llm_provider),
            node_execution_repository,
            agent_run_id,
            tool_execution_repository,
            error_service,
        ),
    )
    graph.add_node(HANDLE_ERROR_NODE, handle_error_node)

    graph.add_edge(START, CHECK_CONVERSATION_MODE_NODE)
    graph.add_conditional_edges(
        CHECK_CONVERSATION_MODE_NODE,
        _route_after_mode_check,
        {
            HANDLE_ERROR_NODE: HANDLE_ERROR_NODE,
            END: END,
            RESOLVE_INTERACTION_NODE: RESOLVE_INTERACTION_NODE,
            FRESH_RESTART_NODE: FRESH_RESTART_NODE,
        },
    )
    graph.add_edge(FRESH_RESTART_NODE, END)
    graph.add_conditional_edges(
        RESOLVE_INTERACTION_NODE,
        _route_after_resolve_interaction,
        {
            HANDLE_ERROR_NODE: HANDLE_ERROR_NODE,
            APPOINTMENT_NODE: APPOINTMENT_NODE,
            AGREEMENT_NODE: AGREEMENT_NODE,
            SPECIALTIES_NODE: SPECIALTIES_NODE,
            TREATMENT_CATALOG_NODE: TREATMENT_CATALOG_NODE,
            HANDOFF_NODE: HANDOFF_NODE,
            QUESTION_NODE: QUESTION_NODE,
            LOCATION_NODE: LOCATION_NODE,
            FALLBACK_NODE: FALLBACK_NODE,
        },
    )
    for node_name in (
        APPOINTMENT_NODE,
        AGREEMENT_NODE,
        SPECIALTIES_NODE,
        TREATMENT_CATALOG_NODE,
        HANDOFF_NODE,
        QUESTION_NODE,
        LOCATION_NODE,
        FALLBACK_NODE,
    ):
        graph.add_conditional_edges(
            node_name,
            _route_after_business_node,
            {HANDLE_ERROR_NODE: HANDLE_ERROR_NODE, END: END},
        )
    graph.add_edge(HANDLE_ERROR_NODE, END)

    return graph


def compile_graph(
    appointment_gateway: AppointmentGateway,
    agreement_gateway: AgreementGateway,
    specialty_gateway: SpecialtyGateway,
    handoff_gateway: HumanHandoffGateway,
    llm_provider: LLMProvider,
    conversation_repository: ConversationRepository,
    patient_gateway: PatientGateway,
    proposal_repositories_provider: ProposalRepositoriesProvider,
    redis_client: Redis,
    confirmation_timeout_seconds: int,
    node_execution_repository: NodeExecutionRepository,
    agent_run_id: str,
    tool_execution_repository: ToolExecutionRepository,
    error_service: ErrorService,
    checkpointer: "BaseCheckpointSaver[Any] | None" = None,
    verification_flow_id: str = "",
    registration_flow_id: str = "",
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compiles the graph, optionally with a checkpointer.

    Checkpointer-agnostic by design: any `BaseCheckpointSaver` implementation
    works here (e.g. `MemorySaver` in tests, `AsyncPostgresSaver` in
    production via `create_postgres_checkpointer_pool`/`create_checkpointer`
    below), so graph wiring can be unit-tested without a real Postgres
    instance or the `langgraph-checkpoint-postgres`/`psycopg` packages
    installed.
    """
    return build_graph(
        appointment_gateway,
        agreement_gateway,
        specialty_gateway,
        handoff_gateway,
        llm_provider,
        conversation_repository,
        patient_gateway,
        proposal_repositories_provider,
        redis_client,
        confirmation_timeout_seconds,
        node_execution_repository,
        agent_run_id,
        tool_execution_repository,
        error_service,
        verification_flow_id=verification_flow_id,
        registration_flow_id=registration_flow_id,
    ).compile(checkpointer=checkpointer)


#: Well under psycopg_pool's own 3600s default — a cloud/managed Postgres
#: or a middlebox typically reaps idle connections long before an hour,
#: and a recycled-too-early connection costs one cheap reconnect while a
#: recycled-too-late one costs a dropped patient reply.
_CHECKPOINTER_POOL_MAX_LIFETIME_SECONDS = 900.0


def create_postgres_checkpointer_pool(conninfo: str) -> "PostgresCheckpointerPool":
    """Creates a dedicated psycopg async connection pool for the LangGraph
    checkpointer.

    Per design decision, this pool is deliberately SEPARATE from the
    SQLAlchemy asyncpg engine (`app.infrastructure.database.session`) —
    `langgraph-checkpoint-postgres` only supports psycopg(3) connections, not
    SQLAlchemy sessions/engines, so the checkpointer manages its own
    connection lifecycle end to end. The pool is returned closed (`open`
    must be awaited by the caller) so callers control connection timing
    (e.g. FastAPI lifespan startup/shutdown).

    Connections are opened with ``autocommit=True`` because
    `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`, which
    Postgres refuses to run inside a transaction block — this matches the
    connection kwargs `AsyncPostgresSaver.from_conn_string` uses internally
    (`autocommit=True, prepare_threshold=0, row_factory=dict_row`).

    `check`/`max_lifetime` are this pool's equivalent of the SQLAlchemy
    engine's `pool_pre_ping=True` (see
    `app.infrastructure.database.session.create_engine`) — that engine got
    this treatment, this separate psycopg pool never did. psycopg_pool
    defaults to NO liveness check and keeps `min_size` connections for up
    to an hour, so a connection the server has since dropped (restart,
    idle reaper, network blip) is handed out as-is and every agent turn
    dies at `aget_state` with `consuming input failed: server closed the
    connection unexpectedly`, which is exactly what happened in
    production: webhooks kept returning 200 (SQLAlchemy path is pre-pinged
    and fine) while the patient got no reply at all.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool: PostgresCheckpointerPool = AsyncConnectionPool(
        conninfo=conninfo,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=AsyncConnectionPool.check_connection,
        max_lifetime=_CHECKPOINTER_POOL_MAX_LIFETIME_SECONDS,
    )
    return pool


#: The domain types this graph puts in `collected_data`, and therefore into
#: every checkpoint. LangGraph warns on deserializing any type not declared
#: here ("Deserializing unregistered type ... This will be blocked in a
#: future version") and will eventually refuse outright — declaring them is
#: what keeps the appointment cursor readable across an upgrade. Only
#: plain, trusted dataclasses of ours belong on this list.
_CHECKPOINT_MSGPACK_MODULES = (
    ("app.domain.value_objects.interactive_button", "InteractiveButton"),
    ("app.domain.value_objects.list_message", "ListRow"),
    ("app.domain.value_objects.list_message", "ListMessage"),
    ("app.domain.entities.specialty", "Specialty"),
    ("app.domain.entities.professional", "Professional"),
    ("app.domain.entities.appointment_slot", "AppointmentSlot"),
    ("app.domain.entities.appointment", "Appointment"),
    ("app.domain.value_objects.date_time_range", "DateTimeRange"),
    ("app.domain.value_objects.appointment_id", "AppointmentId"),
)


async def create_checkpointer(pool: "PostgresCheckpointerPool") -> "AsyncPostgresSaver":
    """Wraps an open psycopg pool in an `AsyncPostgresSaver` and ensures its
    checkpoint tables exist (`AsyncPostgresSaver.setup()`)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    saver = AsyncPostgresSaver(
        pool,
        serde=JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_MSGPACK_MODULES),
    )
    await saver.setup()
    return saver


def build_state_reset_graph(
    checkpointer: "BaseCheckpointSaver[Any]",
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """A dependency-free `AgentState` graph, compiled ONLY so
    `aupdate_state` has something to call it on.

    This session's own brief: the inactivity follow-up worker resets a
    stuck trámite's `collected_data` from OUTSIDE any real turn — no
    `appointment_gateway`/`agreement_gateway`/etc. involved, so building
    the full `compile_graph(...)` just for this would drag in a dozen
    unrelated dependencies the worker has no use for. Verified directly:
    `aupdate_state` against this minimal graph correctly updates the SAME
    `thread_id`'s checkpoint the fully-wired graph reads/writes, because
    both share one checkpointer and the same `AgentState` schema — no node
    here ever actually runs.
    """
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    graph.add_node("noop", lambda _state: {})
    graph.add_edge(START, "noop")
    graph.add_edge("noop", END)
    return graph.compile(checkpointer=checkpointer)
