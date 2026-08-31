import pytest

from app.application.admin.run_queries import RunQueryService
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_node_execution_repository,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_agent_run, make_node_execution, make_tool_execution


@pytest.mark.asyncio
async def test_get_run_detail_returns_none_when_missing():
    service = RunQueryService(
        make_agent_run_repository(),
        make_node_execution_repository(),
        make_tool_execution_repository(),
    )

    assert await service.get_run_detail("missing") is None


@pytest.mark.asyncio
async def test_get_run_detail_aggregates_node_and_tool_executions():
    agent_runs = make_agent_run_repository()
    node_executions = make_node_execution_repository()
    tool_executions = make_tool_execution_repository()

    await agent_runs.save(make_agent_run(id_="run-1"))
    await node_executions.save(make_node_execution(id_="ne-1", agent_run_id="run-1"))
    await tool_executions.save(make_tool_execution(id_="te-1", agent_run_id="run-1"))

    service = RunQueryService(agent_runs, node_executions, tool_executions)
    detail = await service.get_run_detail("run-1")

    assert detail is not None
    assert detail.agent_run.id == "run-1"
    assert [ne.id for ne in detail.node_executions] == ["ne-1"]
    assert [te.id for te in detail.tool_executions] == ["te-1"]
