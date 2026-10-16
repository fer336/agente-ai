from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Literal

from app.application.admin.graph_topology import get_graph_topology
from app.domain.entities.node_execution import FAILED, RUNNING, NodeExecution
from app.domain.repositories.node_execution_repository import NodeExecutionRepository

Window = Literal["15m", "1h", "24h"]

WINDOWS: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
}

#: Hard cap on rows aggregated per call; `truncated` reports when it was hit.
ROW_CAP = 20000


@dataclass(frozen=True)
class NodeState:
    """Aggregated state of one node within the window."""

    count: int
    failed: int
    running: int
    last_status: str
    last_at: datetime
    avg_ms: float | None
    p50_ms: float | None
    last_error_id: str | None
    last_run_id: str


@dataclass(frozen=True)
class GraphState:
    generated_at: datetime
    window: str
    nodes: dict[str, NodeState]
    unmapped: tuple[str, ...]
    truncated: bool


class GraphStateQueryService:
    """Read-only per-node aggregates backing `GET /admin/api/graphs/state`."""

    def __init__(self, node_executions: NodeExecutionRepository, row_cap: int = ROW_CAP) -> None:
        self._node_executions = node_executions
        self._row_cap = row_cap

    async def get_state(self, window: Window, now: datetime) -> GraphState:
        rows = await self._node_executions.list_since(now - WINDOWS[window], self._row_cap)
        by_node: dict[str, list[NodeExecution]] = {}
        for row in rows:  # newest first
            by_node.setdefault(row.node_name, []).append(row)

        known = {node.id for graph in get_graph_topology() for node in graph.nodes if node.traced}
        return GraphState(
            generated_at=now,
            window=window,
            nodes={name: _aggregate(group) for name, group in by_node.items()},
            unmapped=tuple(sorted(name for name in by_node if name not in known)),
            truncated=len(rows) >= self._row_cap,
        )


def _aggregate(newest_first: list[NodeExecution]) -> NodeState:
    latest = newest_first[0]
    # RUNNING rows carry a placeholder duration (0), not a measurement.
    durations = [row.duration_ms for row in newest_first if row.status != RUNNING]
    last_error_id = next((row.error_id for row in newest_first if row.error_id), None)
    return NodeState(
        count=len(newest_first),
        failed=sum(1 for row in newest_first if row.status == FAILED),
        running=sum(1 for row in newest_first if row.status == RUNNING),
        last_status=latest.status,
        last_at=latest.started_at,
        avg_ms=sum(durations) / len(durations) if durations else None,
        p50_ms=float(median(durations)) if durations else None,
        last_error_id=last_error_id,
        last_run_id=latest.agent_run_id,
    )
