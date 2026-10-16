from datetime import UTC, datetime

import pytest

from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.infrastructure.database.fake_node_execution_repository import (
    FakeNodeExecutionRepository,
)
from tests.fixtures.gateways import make_node_execution_repository
from tests.fixtures.seed_objects import make_node_execution


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_node_execution_repository()
    node_execution = make_node_execution(id_="ne-1")

    await repository.save(node_execution)
    fetched = await repository.get_by_id("ne-1")

    assert fetched is node_execution


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_node_execution_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_by_agent_run_id_returns_only_matching_executions_in_order():
    repository = make_node_execution_repository()
    await repository.save(
        make_node_execution(
            id_="ne-2", agent_run_id="run-1", started_at=datetime(2026, 8, 11, 9, 1, tzinfo=UTC)
        )
    )
    await repository.save(
        make_node_execution(
            id_="ne-1", agent_run_id="run-1", started_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
        )
    )
    await repository.save(make_node_execution(id_="ne-3", agent_run_id="run-2"))

    executions = await repository.get_by_agent_run_id("run-1")

    assert [execution.id for execution in executions] == ["ne-1", "ne-2"]


def test_fake_node_execution_repository_satisfies_protocol():
    assert isinstance(FakeNodeExecutionRepository(), NodeExecutionRepository)


@pytest.mark.asyncio
async def test_list_since_filters_orders_newest_first_and_applies_limit():
    repository = make_node_execution_repository()
    for id_, minute in (("old", 0), ("edge", 10), ("mid", 20), ("new", 30)):
        await repository.save(
            make_node_execution(id_=id_, started_at=datetime(2026, 8, 11, 9, minute, tzinfo=UTC))
        )
    since = datetime(2026, 8, 11, 9, 10, tzinfo=UTC)

    all_recent = await repository.list_since(since, limit=10)
    capped = await repository.list_since(since, limit=2)

    assert [e.id for e in all_recent] == ["new", "mid", "edge"]
    assert [e.id for e in capped] == ["new", "mid"]
