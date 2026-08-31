import logging
from datetime import UTC, datetime
from uuid import uuid4

from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.errors.error_service import ErrorService
from app.application.errors.error_types import UNEXPECTED_EXCEPTION
from app.domain.entities.error_record import SOURCE_LANGGRAPH
from app.domain.entities.node_execution import COMPLETED, FAILED, NodeExecution
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository
from app.infrastructure.observability.trace_context import TraceContext, use_trace_context

logger = logging.getLogger(__name__)


def _summarize_input(state: AgentState) -> str:
    """Builds a short, privacy-safe summary of a node's input state.

    Deliberately excludes `user_message` — it can carry a patient's free-text
    identification message (name + DNI, PRD.md §32) or other PII, which
    PRD.md §41's "never store unnecessary sensitive information" mandate
    applies to in spirit even though that line is written about tool calls.
    """
    parts = [f"intent={state.get('intent')}"]
    if state.get("button_payload") is not None:
        parts.append("button=yes")
    stage = state.get("collected_data", {}).get("stage")
    if stage is not None:
        parts.append(f"stage={stage}")
    return " ".join(parts)


def _summarize_output(result: dict[str, object]) -> str:
    parts = []
    if "intent" in result:
        parts.append(f"intent={result['intent']}")
    if "response_text" in result:
        text = result["response_text"]
        parts.append(f"response_len={len(text) if isinstance(text, str) else 0}")
    if result.get("requires_handoff"):
        parts.append("handoff=yes")
    collected_data = result.get("collected_data")
    if isinstance(collected_data, dict) and collected_data.get("stage") is not None:
        parts.append(f"stage={collected_data['stage']}")
    return " ".join(parts) if parts else "no-op"


def with_error_handling(
    node_name: str,
    node: AgentNode,
    node_execution_repository: NodeExecutionRepository,
    agent_run_id: str,
    tool_execution_repository: ToolExecutionRepository,
    error_service: ErrorService,
) -> AgentNode:
    """Wraps a node so an unhandled exception routes to `handle_error` (PRD.md §30)
    and every call is recorded as a `NodeExecution` (PRD.md §40).

    A bare try/except per node — this only guarantees "un error técnico no
    deberá dejar la conversación en un estado inconsistente" by catching
    the exception and routing to `handle_error` instead of crashing the
    graph run.

    Also opens this node's `TraceContext` (PRD.md §41) for the duration of
    the call — any gateway the node's use cases go on to invoke reads it
    via `app.infrastructure.observability.trace_context.get_trace_context`
    to record its own `ToolExecution`, tagged with THIS node's
    `node_execution_id`, without the gateway's own Protocol needing to know
    about tracing at all.

    An unhandled node exception is always reported to `ErrorService` as
    `source=langgraph`, `error_type=unexpected_exception` (PRD.md §45/§52)
    — by construction, anything that reaches this except clause is
    something no more specific error handling upstream classified, which
    is exactly what `unexpected_exception` means (PRD.md §43.3). The
    resulting `ErrorRecord.id` becomes this `NodeExecution.error_id`.

    Written once, after the node call finishes (success or caught
    exception) — see `NodeExecution`'s own docstring for why a node call
    has no useful intermediate `running` state to persist.
    """

    async def wrapped(state: AgentState) -> dict[str, object]:
        node_execution_id = str(uuid4())
        started_at = datetime.now(UTC)
        input_summary = _summarize_input(state)
        context = TraceContext(
            agent_run_id=agent_run_id,
            node_execution_id=node_execution_id,
            tool_execution_repository=tool_execution_repository,
            error_service=error_service,
        )
        try:
            with use_trace_context(context):
                result = await node(state)
        except Exception as exc:
            finished_at = datetime.now(UTC)
            logger.exception(
                "agent_node.error node=%s conversation=%s",
                node_name,
                state["conversation_id"],
            )
            error = await error_service.report(
                source=SOURCE_LANGGRAPH,
                error_type=UNEXPECTED_EXCEPTION,
                message=f"Node '{node_name}' raised an unhandled exception",
                agent_run_id=agent_run_id,
                technical_detail=repr(exc),
                operation=node_name,
            )
            await node_execution_repository.save(
                NodeExecution(
                    id=node_execution_id,
                    agent_run_id=agent_run_id,
                    node_name=node_name,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=FAILED,
                    input_summary=input_summary,
                    output_summary="unhandled exception",
                    duration_ms=int((finished_at - started_at).total_seconds() * 1000),
                    error_id=error.id,
                )
            )
            return {"error": node_name}

        finished_at = datetime.now(UTC)
        await node_execution_repository.save(
            NodeExecution(
                id=node_execution_id,
                agent_run_id=agent_run_id,
                node_name=node_name,
                started_at=started_at,
                finished_at=finished_at,
                status=COMPLETED,
                input_summary=input_summary,
                output_summary=_summarize_output(result),
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
                error_id=None,
            )
        )
        return result

    return wrapped
