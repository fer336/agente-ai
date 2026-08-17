from datetime import UTC, datetime

import pytest

from app.domain.repositories.tool_execution_repository import ToolExecutionRepository
from app.infrastructure.database.fake_tool_execution_repository import (
    FakeToolExecutionRepository,
)
from tests.fixtures.gateways import make_tool_execution_repository
from tests.fixtures.seed_objects import make_tool_execution


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_tool_execution_repository()
    tool_execution = make_tool_execution(id_="te-1")

    await repository.save(tool_execution)
    fetched = await repository.get_by_id("te-1")

    assert fetched is tool_execution


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_tool_execution_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_by_agent_run_id_returns_only_matching_executions_in_order():
    repository = make_tool_execution_repository()
    await repository.save(
        make_tool_execution(
            id_="te-2", agent_run_id="run-1", created_at=datetime(2026, 8, 11, 9, 1, tzinfo=UTC)
        )
    )
    await repository.save(
        make_tool_execution(
            id_="te-1", agent_run_id="run-1", created_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
        )
    )
    await repository.save(make_tool_execution(id_="te-3", agent_run_id="run-2"))

    executions = await repository.get_by_agent_run_id("run-1")

    assert [execution.id for execution in executions] == ["te-1", "te-2"]


def test_fake_tool_execution_repository_satisfies_protocol():
    assert isinstance(FakeToolExecutionRepository(), ToolExecutionRepository)
