from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.application.errors.error_service import ErrorService
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository


@dataclass(frozen=True)
class TraceContext:
    """Ambient tracing context for the currently-executing LangGraph node
    (PRD.md §40-41, §45).

    Threading `agent_run_id`/`tool_execution_repository`/`error_service`
    through every `AppointmentGateway`/`MessagingGateway` Protocol method —
    used pervasively by application-layer use cases that have no concept of
    "current agent run" — would mean an invasive signature change
    cascading through dozens of already-tested call sites, just to plumb a
    correlation id. A `contextvars.ContextVar` instead — the same pattern
    OpenTelemetry/structlog use for exactly this kind of cross-cutting
    concern — set once per node call (`with_error_handling`) and read
    implicitly at the gateway boundary. `asyncio` correctly propagates a
    `ContextVar` across a single task's own `await` chain, which is all
    one node's execution ever is.
    """

    agent_run_id: str
    node_execution_id: str
    tool_execution_repository: ToolExecutionRepository
    error_service: ErrorService


_current: ContextVar["TraceContext | None"] = ContextVar("_current_trace_context", default=None)


@contextmanager
def use_trace_context(context: TraceContext) -> Iterator[None]:
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)


def get_trace_context() -> TraceContext | None:
    """Returns the ambient trace context, or `None` when called outside of
    a graph node's execution (e.g. a gateway exercised directly by a unit
    test) — callers must treat `None` as "nothing to record", not an error.
    """
    return _current.get()
