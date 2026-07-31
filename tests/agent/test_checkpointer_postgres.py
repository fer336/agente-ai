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

from app.agent.graph import compile_graph, create_checkpointer, create_postgres_checkpointer_pool
from app.config.settings import get_settings
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


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


def _initial_state(conversation_id: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "message_ids": ["msg-1"],
        "user_message": "Necesito un turno",
        "intent": "schedule_appointment",
        "collected_data": {},
        "missing_fields": [],
        "pending_action_id": None,
        "response_text": None,
        "requires_handoff": False,
    }


@pytest.fixture
async def postgres_pool():
    pool = create_postgres_checkpointer_pool(_conninfo())
    try:
        await pool.open()
    except OSError as exc:
        pytest.skip(f"Postgres not reachable for checkpointer test: {exc}")
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_asyncpostgressaver_persists_and_restores_state_across_graph_invocations(
    postgres_pool,
):
    checkpointer = await create_checkpointer(postgres_pool)
    gateway = FakeDentalinkGateway(available_slots=[_future_slot()])
    compiled = compile_graph(gateway, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "conv-postgres-checkpoint-1"}}

    await compiled.ainvoke(_initial_state("conv-postgres-checkpoint-1"), config=config)
    restored = await compiled.aget_state(config)

    assert restored.values["conversation_id"] == "conv-postgres-checkpoint-1"
    assert len(restored.values["collected_data"]["available_slots"]) == 1
