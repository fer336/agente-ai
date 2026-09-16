from contextlib import asynccontextmanager

import pytest

from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from app.workers.follow_up_worker import FollowUpWorkerRepositories, run_follow_up_loop
from tests.fixtures.gateways import (
    make_contact_repository,
    make_conversation_repository,
    make_message_repository,
    make_send_reply_use_case,
)


async def _checkpointer_provider():
    return None


def _repositories_provider_counting(calls: list[int]):
    @asynccontextmanager
    async def provider():
        calls.append(len(calls))
        yield FollowUpWorkerRepositories(
            scheduled_actions=FakeScheduledActionRepository(),
            messages=make_message_repository(),
            conversations=make_conversation_repository(),
            contacts=make_contact_repository(),
        )

    return provider


@pytest.mark.asyncio
async def test_run_follow_up_loop_ticks_the_configured_number_of_times():
    # Regression: nothing ever turned `run_follow_up_tick` into a real,
    # running loop — `app.main`'s own `lifespan` docstring claimed it did,
    # but no code actually started it. This proves the wrapper this fix
    # adds actually polls repeatedly rather than running once and stopping.
    calls: list[int] = []

    await run_follow_up_loop(
        _repositories_provider_counting(calls),
        _checkpointer_provider,
        make_send_reply_use_case(),
        interval_seconds=0,
        batch_limit=50,
        reset_delay_seconds=1200,
        max_iterations=3,
    )

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_run_follow_up_loop_survives_a_failing_tick():
    # A single tick's failure (a transient DB error, mid-poll) must never
    # kill the whole background task — nothing else would ever restart it
    # for the rest of the process's lifetime.
    attempts = {"count": 0}

    @asynccontextmanager
    async def flaky_repositories_provider():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        yield FollowUpWorkerRepositories(
            scheduled_actions=FakeScheduledActionRepository(),
            messages=make_message_repository(),
            conversations=make_conversation_repository(),
            contacts=make_contact_repository(),
        )

    await run_follow_up_loop(
        flaky_repositories_provider,
        _checkpointer_provider,
        make_send_reply_use_case(),
        interval_seconds=0,
        batch_limit=50,
        reset_delay_seconds=1200,
        max_iterations=2,
    )

    assert attempts["count"] == 2
