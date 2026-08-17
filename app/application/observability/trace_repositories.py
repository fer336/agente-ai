from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.error_repository import ErrorRepository
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository


@dataclass(frozen=True)
class TraceRepositories:
    """Bundles the four repositories PRD.md §38's traceability layer needs
    (`agent_runs`/`node_executions`/`tool_executions`/`errors`, §39-42).

    Shared across `LangGraphAgentInvoker` (agent runs + node executions),
    the gateways (tool executions), and `ErrorService` (errors) — owned by
    none of them individually, unlike e.g. `ProposalRepositories`.
    """

    agent_runs: AgentRunRepository
    node_executions: NodeExecutionRepository
    tool_executions: ToolExecutionRepository
    errors: ErrorRepository


# A zero-arg async context manager factory yielding a fresh `TraceRepositories`
# for one unit of work. Production implementation MUST commit the underlying
# transaction on success (see `app.api.dependencies.repositories.
# open_sqlalchemy_trace_repositories`) — this data exists specifically to be
# durably queryable later (PRD.md §44's admin panel, incident review), unlike
# the conversational repositories' own "same-session-only" default.
TraceRepositoriesProvider = Callable[[], AbstractAsyncContextManager[TraceRepositories]]
