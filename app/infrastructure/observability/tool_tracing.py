from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import uuid4

from app.domain.entities.tool_execution import COMPLETED, FAILED, ToolExecution
from app.infrastructure.observability.trace_context import get_trace_context

T = TypeVar("T")


async def traced_call(
    *,
    tool_name: str,
    provider: str,
    operation: str,
    request_summary: str,
    call: Callable[[], Awaitable[T]],
    response_summary: Callable[[T], str] | None = None,
    http_status_of: Callable[[Exception], str | None] | None = None,
    error_type_of: Callable[[Exception], str] | None = None,
) -> T:
    """Runs `call()`, recording a `ToolExecution` around it (PRD.md §41).

    A no-op wrapper when there is no ambient `TraceContext` (e.g. a gateway
    exercised directly by a unit test, outside a graph node's execution) —
    `call()` still runs, nothing is recorded. `request_summary` and
    `response_summary` are always caller-supplied, pre-built safe strings —
    this function never serializes `call`'s arguments or return value
    itself, so a gateway can never accidentally leak a raw `Patient` or
    similar into a summary just by using this helper.

    `error_type_of` (when given) also reports a classified `ErrorRecord`
    via `context.error_service` on failure (PRD.md §45/§52) and links it
    via `ToolExecution.error_id` — omitted entirely when the caller has no
    error_type mapping for this provider's exceptions yet.
    """
    context = get_trace_context()
    started_at = datetime.now(UTC)
    try:
        result = await call()
    except Exception as exc:
        if context is not None:
            error_id = None
            if error_type_of is not None:
                error = await context.error_service.report(
                    source=provider,
                    error_type=error_type_of(exc),
                    message=str(exc),
                    agent_run_id=context.agent_run_id,
                    technical_detail=repr(exc),
                )
                error_id = error.id
            await context.tool_execution_repository.save(
                ToolExecution(
                    id=str(uuid4()),
                    agent_run_id=context.agent_run_id,
                    node_execution_id=context.node_execution_id,
                    tool_name=tool_name,
                    provider=provider,
                    operation=operation,
                    request_summary=request_summary,
                    response_summary=None,
                    status=FAILED,
                    http_status=http_status_of(exc) if http_status_of is not None else None,
                    duration_ms=int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                    error_id=error_id,
                    created_at=datetime.now(UTC),
                )
            )
        raise
    else:
        if context is not None:
            await context.tool_execution_repository.save(
                ToolExecution(
                    id=str(uuid4()),
                    agent_run_id=context.agent_run_id,
                    node_execution_id=context.node_execution_id,
                    tool_name=tool_name,
                    provider=provider,
                    operation=operation,
                    request_summary=request_summary,
                    response_summary=(
                        response_summary(result) if response_summary is not None else None
                    ),
                    status=COMPLETED,
                    http_status="200",
                    duration_ms=int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                    error_id=None,
                    created_at=datetime.now(UTC),
                )
            )
        return result
