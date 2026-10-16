from datetime import UTC, datetime, timedelta

import pytest

from app.application.admin.graph_state_queries import GraphStateQueryService
from app.application.admin.graph_topology import get_graph_topology
from app.domain.entities.node_execution import COMPLETED, FAILED, RUNNING
from tests.fixtures.gateways import make_node_execution_repository
from tests.fixtures.seed_objects import make_node_execution

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _traced_node() -> str:
    for graph in get_graph_topology():
        for node in graph.nodes:
            if node.traced:
                return node.id
    raise AssertionError("no traced node in topology")


NODE = _traced_node()


async def _service(*rows, row_cap: int = 20000) -> GraphStateQueryService:
    repository = make_node_execution_repository()
    for row in rows:
        await repository.save(row)
    return GraphStateQueryService(repository, row_cap=row_cap)


def _row(id_: str, minutes_ago: float, node: str = NODE, **kwargs):
    return make_node_execution(
        id_=id_,
        node_name=node,
        started_at=NOW - timedelta(minutes=minutes_ago),
        finished_at=NOW - timedelta(minutes=minutes_ago),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_empty_window_returns_no_nodes():
    state = await (await _service()).get_state("15m", NOW)

    assert state.nodes == {}
    assert state.unmapped == ()
    assert state.truncated is False
    assert state.window == "15m"
    assert state.generated_at == NOW


@pytest.mark.asyncio
async def test_counts_failed_running_and_duration_stats():
    service = await _service(
        _row("a", 5, status=COMPLETED, duration_ms=10),
        _row("b", 4, status=COMPLETED, duration_ms=30),
        _row("c", 3, status=FAILED, duration_ms=50, error_id="err-1", agent_run_id="run-c"),
        _row("d", 1, status=RUNNING, duration_ms=0, agent_run_id="run-d"),
    )

    state = await service.get_state("15m", NOW)
    node = state.nodes[NODE]

    assert node.count == 4
    assert node.failed == 1
    assert node.running == 1
    assert node.last_status == RUNNING
    assert node.last_at == NOW - timedelta(minutes=1)
    assert node.last_run_id == "run-d"
    assert node.last_error_id == "err-1"
    # RUNNING placeholder (duration 0) is excluded from duration stats.
    assert node.avg_ms == 30
    assert node.p50_ms == 30


@pytest.mark.asyncio
async def test_p50_is_median_of_finished_durations():
    service = await _service(
        _row("a", 5, duration_ms=10),
        _row("b", 4, duration_ms=20),
        _row("c", 3, duration_ms=100),
        _row("d", 2, duration_ms=200),
    )

    node = (await service.get_state("15m", NOW)).nodes[NODE]

    assert node.avg_ms == 82.5
    assert node.p50_ms == 60


@pytest.mark.asyncio
async def test_only_running_rows_yield_no_duration_stats_or_error():
    service = await _service(_row("a", 1, status=RUNNING, duration_ms=0))

    node = (await service.get_state("15m", NOW)).nodes[NODE]

    assert node.avg_ms is None
    assert node.p50_ms is None
    assert node.last_error_id is None


@pytest.mark.asyncio
async def test_last_error_id_is_from_newest_row_with_an_error():
    service = await _service(
        _row("a", 9, status=FAILED, error_id="err-old"),
        _row("b", 5, status=FAILED, error_id="err-new"),
        _row("c", 1, status=COMPLETED),
    )

    node = (await service.get_state("15m", NOW)).nodes[NODE]

    assert node.last_error_id == "err-new"
    assert node.last_status == COMPLETED


@pytest.mark.asyncio
async def test_unmapped_lists_node_names_absent_from_traced_topology():
    service = await _service(_row("a", 1), _row("b", 2, node="ghost"), _row("c", 3, node="alien"))

    state = await service.get_state("15m", NOW)

    assert state.unmapped == ("alien", "ghost")
    assert "ghost" in state.nodes


@pytest.mark.asyncio
async def test_truncated_when_row_cap_is_hit():
    service = await _service(_row("a", 1), _row("b", 2), _row("c", 3), row_cap=2)

    state = await service.get_state("15m", NOW)

    assert state.truncated is True
    assert state.nodes[NODE].count == 2
    assert state.nodes[NODE].last_at == NOW - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_not_truncated_below_cap():
    state = await (await _service(_row("a", 1), row_cap=2)).get_state("15m", NOW)

    assert state.truncated is False


@pytest.mark.parametrize(("window", "minutes"), [("15m", 15), ("1h", 60), ("24h", 24 * 60)])
@pytest.mark.asyncio
async def test_window_boundary_is_inclusive_and_excludes_older(window, minutes):
    service = await _service(
        _row("inside", minutes - 0.01),
        _row("edge", minutes),
        _row("outside", minutes + 0.01),
    )

    node = (await service.get_state(window, NOW)).nodes[NODE]

    assert node.count == 2
