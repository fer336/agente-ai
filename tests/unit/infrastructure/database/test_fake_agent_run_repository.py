from datetime import UTC, datetime

import pytest

from app.domain.entities.agent_run import COMPLETED, RUNNING
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.value_objects.conversation_id import ConversationId
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


@pytest.mark.asyncio
async def test_get_by_conversation_id_orders_newest_first():
    repository = make_agent_run_repository()
    await repository.save(
        make_agent_run(
            id_="run-earlier",
            conversation_id="conv-1",
            status=COMPLETED,
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        )
    )
    await repository.save(
        make_agent_run(
            id_="run-later",
            conversation_id="conv-1",
            status=RUNNING,
            started_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        )
    )
    await repository.save(
        make_agent_run(id_="run-other-conv", conversation_id="conv-2", status=COMPLETED)
    )

    fetched = await repository.get_by_conversation_id(ConversationId("conv-1"))

    assert [run.id for run in fetched] == ["run-later", "run-earlier"]


@pytest.mark.asyncio
async def test_get_latest_by_conversation_id_returns_none_when_no_runs():
    repository = make_agent_run_repository()

    assert await repository.get_latest_by_conversation_id(ConversationId("conv-none")) is None


@pytest.mark.asyncio
async def test_get_latest_by_conversation_id_returns_the_most_recent():
    repository = make_agent_run_repository()
    await repository.save(
        make_agent_run(
            id_="run-a",
            conversation_id="conv-1",
            started_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        )
    )
    await repository.save(
        make_agent_run(
            id_="run-b",
            conversation_id="conv-1",
            started_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        )
    )

    latest = await repository.get_latest_by_conversation_id(ConversationId("conv-1"))

    assert latest is not None
    assert latest.id == "run-b"
