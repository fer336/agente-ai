from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.search_availability import create_search_availability_node
from app.agent.state import AgentState
from app.domain.repositories.gateways import AppointmentGateway

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

#: Name of the example tool→use-case→gateway node (architecture doc §5.2).
SEARCH_AVAILABILITY_NODE = "search_availability"


def build_graph(
    gateway: AppointmentGateway,
) -> StateGraph[AgentState, None, AgentState, AgentState]:
    """Builds the (uncompiled) agent graph wired with the example
    `search_availability` node.

    Kept separate from `compile_graph` so tests can inspect graph structure
    (nodes/edges) without needing a checkpointer at all.
    """
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    graph.add_node(SEARCH_AVAILABILITY_NODE, create_search_availability_node(gateway))
    graph.add_edge(START, SEARCH_AVAILABILITY_NODE)
    graph.add_edge(SEARCH_AVAILABILITY_NODE, END)
    return graph


def compile_graph(
    gateway: AppointmentGateway,
    checkpointer: "BaseCheckpointSaver[Any] | None" = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compiles the graph, optionally with a checkpointer.

    Checkpointer-agnostic by design: any `BaseCheckpointSaver` implementation
    works here (e.g. `MemorySaver` in tests, `AsyncPostgresSaver` in
    production via `create_postgres_checkpointer_pool`/`create_checkpointer`
    below), so graph wiring can be unit-tested without a real Postgres
    instance or the `langgraph-checkpoint-postgres`/`psycopg` packages
    installed.
    """
    return build_graph(gateway).compile(checkpointer=checkpointer)


def create_postgres_checkpointer_pool(conninfo: str) -> "AsyncConnectionPool":
    """Creates a dedicated psycopg async connection pool for the LangGraph
    checkpointer.

    Per design decision, this pool is deliberately SEPARATE from the
    SQLAlchemy asyncpg engine (`app.infrastructure.database.session`) —
    `langgraph-checkpoint-postgres` only supports psycopg(3) connections, not
    SQLAlchemy sessions/engines, so the checkpointer manages its own
    connection lifecycle end to end. The pool is returned closed (`open`
    must be awaited by the caller) so callers control connection timing
    (e.g. FastAPI lifespan startup/shutdown).
    """
    from psycopg_pool import AsyncConnectionPool

    return AsyncConnectionPool(conninfo=conninfo, open=False)


async def create_checkpointer(pool: "AsyncConnectionPool") -> "AsyncPostgresSaver":
    """Wraps an open psycopg pool in an `AsyncPostgresSaver` and ensures its
    checkpoint tables exist (`AsyncPostgresSaver.setup()`)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver
