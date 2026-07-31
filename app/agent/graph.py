from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.search_availability import create_search_availability_node
from app.agent.state import AgentState
from app.domain.repositories.gateways import AppointmentGateway

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

    #: Pool typed with the dict row factory `AsyncPostgresSaver` requires —
    #: matches what `create_postgres_checkpointer_pool` actually constructs.
    PostgresCheckpointerPool = AsyncConnectionPool[AsyncConnection[dict[str, Any]]]

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
    """
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool: PostgresCheckpointerPool = AsyncConnectionPool(
        conninfo=conninfo,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    return pool


async def create_checkpointer(pool: "PostgresCheckpointerPool") -> "AsyncPostgresSaver":
    """Wraps an open psycopg pool in an `AsyncPostgresSaver` and ensures its
    checkpoint tables exist (`AsyncPostgresSaver.setup()`)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver
