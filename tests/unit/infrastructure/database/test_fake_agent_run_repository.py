import pytest

from app.domain.entities.agent_run import COMPLETED
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.infrastructure.database.fake_agent_run_repository import FakeAgentRunRepository
from tests.fixtures.gateways import make_agent_run_repository
from tests.fixtures.seed_objects import make_agent_run


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_agent_run_repository()
    agent_run = make_agent_run(id_="run-1")

    await repository.save(agent_run)
    fetched = await repository.get_by_id("run-1")

    assert fetched is agent_run


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_agent_run_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_save_upserts_by_id():
    repository = make_agent_run_repository()
    await repository.save(make_agent_run(id_="run-1", status="running"))

    await repository.save(make_agent_run(id_="run-1", status=COMPLETED))

    fetched = await repository.get_by_id("run-1")
    assert fetched is not None
    assert fetched.status == COMPLETED


def test_fake_agent_run_repository_satisfies_protocol():
    assert isinstance(FakeAgentRunRepository(), AgentRunRepository)
