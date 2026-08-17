"""Real Postgres-backed checkpointer persistence test (design Testing
Strategy: "Agent | Graph cycle + checkpointer persistence/restore | ...
against real Postgres").

Requires `psycopg[binary,pool]` + `langgraph-checkpoint-postgres` installed
AND a reachable Postgres instance (`docker-compose up -d postgres`, per the
tasks doc's Unit 3 runtime harness: `pytest tests/agent -k checkpointer`).

Neither the packages nor a running Postgres are available in the sandbox
this test was authored in — both guards below make it skip gracefully there
while still running for real once the environment provides them.
"""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("psycopg_pool", reason="psycopg[binary,pool] not installed in this environment")
pytest.importorskip(
    "langgraph.checkpoint.postgres.aio",
    reason="langgraph-checkpoint-postgres not installed in this environment",
)

from psycopg_pool import PoolTimeout

from app.agent.graph import compile_graph, create_checkpointer, create_postgres_checkpointer_pool
from app.config.settings import get_settings
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_error_service,
    make_node_execution_repository,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_conversation


def _conninfo() -> str:
    settings = get_settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _future_slot() -> AppointmentSlot:
    now = datetime.now(UTC)
    return AppointmentSlot(
        id="slot-1",
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(now + timedelta(days=1), now + timedelta(days=1, hours=1)),
    )


@pytest.fixture
async def postgres_pool():
    pool = create_postgres_checkpointer_pool(_conninfo())
    try:
        # `wait=True` makes `open()` actually attempt a connection and
        # raise on failure instead of the default `wait=False`, which
        # returns immediately and only surfaces connection errors much
        # later (and, in `AsyncPostgresSaver.setup()`'s case, after
        # retrying far longer than is useful for a test skip guard).
        await pool.open(wait=True, timeout=5)
    except (OSError, PoolTimeout) as exc:
        pytest.skip(f"Postgres not reachable for checkpointer test: {exc}")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_asyncpostgressaver_persists_and_restores_state_across_graph_invocations(
    postgres_pool,
):
    checkpointer = await create_checkpointer(postgres_pool)
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="conv-postgres-checkpoint-1", mode="agent")
    )
    compiled = compile_graph(
        appointment_gateway=FakeDentalinkGateway(available_slots=[_future_slot()]),
        agreement_gateway=FakeAgreementGateway(),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversation_repository,
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "conv-postgres-checkpoint-1"}}

    await compiled.ainvoke(
        make_agent_state(
            conversation_id="conv-postgres-checkpoint-1", user_message="Quiero un turno"
        ),
        config=config,
    )
    restored = await compiled.aget_state(config)

    assert restored.values["conversation_id"] == "conv-postgres-checkpoint-1"
