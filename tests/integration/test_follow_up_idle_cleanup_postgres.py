"""The idle cleanup must never wait on a lock that its own tick keeps held.

`run_follow_up_loop` claims a due `conversation_idle_reset` row with an UPDATE
inside the tick's session and keeps that row locked until the tick commits.
The cleanup used to rotate the workflow generation through a SECOND, independent
session. When any other transaction (e.g. an inbound message being ingested)
held the conversation row and was itself waiting for the claimed idle row, the
tick waited on the rotation in Python while the rotation waited in Postgres on
that other transaction: a cycle Postgres cannot see, so the claim stayed locked
forever.

Runs only with `INTEGRATION_DB_TESTS_ENABLED=true` against a disposable Postgres
(see `conftest.db_session`). It exercises the production wiring on real tables.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import _get_session_factory
from app.api.dependencies.repositories import (
    open_sqlalchemy_follow_up_worker_repositories,
    open_sqlalchemy_message_repositories,
    open_sqlalchemy_workflow_session_repositories,
)
from app.api.dependencies.session_cleanup import build_idle_cleanup_use_case
from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
)
from app.application.messages.inbound_message_dto import InboundMessageDTO
from app.application.messages.ingest_message import IngestMessageUseCase
from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.models.contact import ContactModel
from app.infrastructure.database.models.conversation import ConversationModel
from app.infrastructure.database.models.scheduled_action import ScheduledActionModel
from app.infrastructure.database.repositories.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from app.infrastructure.database.repositories.scheduled_action_repository import (
    SqlAlchemyScheduledActionRepository,
)
from app.workers.follow_up_worker import run_follow_up_loop

CONVERSATION = "conv-idle"
ACTION = "idle-1"
TICK_TIMEOUT_SECONDS = 15


class _NoopSendReply:
    async def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("an idle reset never sends a message")


@pytest.fixture
async def production_session_factory(db_session: AsyncSession) -> AsyncIterator[None]:
    """Points the process-wide session factory used by the providers at the test DB."""
    _get_session_factory.cache_clear()
    yield
    factory = _get_session_factory()
    await factory.kw["bind"].dispose()
    _get_session_factory.cache_clear()


@pytest.fixture
async def due_idle_action(db_session: AsyncSession) -> None:
    db_session.add(ContactModel(id="contact-idle", phone="+5491100000077"))
    await db_session.flush()
    db_session.add(ConversationModel(id=CONVERSATION, contact_id="contact-idle", mode="agent"))
    await db_session.flush()
    db_session.add(
        ScheduledActionModel(
            id=ACTION,
            conversation_id=CONVERSATION,
            pending_action_id=None,
            action_type=CONVERSATION_IDLE_RESET_ACTION,
            status="scheduled",
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
            idempotency_key="conversation_idle_reset:idle-1",
            attempts=0,
        )
    )
    await db_session.commit()


async def _run_one_production_tick() -> None:
    await run_follow_up_loop(
        open_sqlalchemy_follow_up_worker_repositories,
        _checkpointer_provider(MemorySaver()),
        _NoopSendReply(),  # type: ignore[arg-type]
        interval_seconds=1,
        batch_limit=10,
        reset_delay_seconds=60,
        max_iterations=1,
        cleanup_factory=build_idle_cleanup_use_case,
    )


def _checkpointer_provider(checkpointer: MemorySaver):
    async def provide() -> MemorySaver:
        return checkpointer

    return provide


async def _generation_and_status(db_session: AsyncSession) -> tuple[int, str]:
    await db_session.rollback()
    generation = (
        await db_session.execute(
            text("select workflow_session_generation from conversations where id = :id"),
            {"id": CONVERSATION},
        )
    ).scalar_one()
    status = (
        await db_session.execute(
            text("select status from scheduled_actions where id = :id"), {"id": ACTION}
        )
    ).scalar_one()
    await db_session.rollback()
    return generation, status


async def test_production_tick_cleans_an_idle_conversation(
    production_session_factory, due_idle_action, db_session
):
    initial_generation, _ = await _generation_and_status(db_session)

    await asyncio.wait_for(_run_one_production_tick(), timeout=TICK_TIMEOUT_SECONDS)

    generation, status = await _generation_and_status(db_session)
    assert generation == initial_generation + 1
    assert status == "executed"


async def test_tick_does_not_hang_when_an_ingest_transaction_holds_the_conversation(
    production_session_factory, due_idle_action, db_session
):
    """An inbound message locks the conversation, then wants to cancel the idle row the
    tick already claimed. The tick must end (commit or fail fast), never wait forever."""
    factory = _get_session_factory()
    ingest_session = factory()
    ingest_conversations = SqlAlchemyConversationRepository(ingest_session)
    ingest_actions = SqlAlchemyScheduledActionRepository(ingest_session)

    conversation = await ingest_conversations.get_by_id(ConversationId(value=CONVERSATION))
    assert conversation is not None
    conversation.workflow_last_activity_at = datetime.now(UTC)
    await ingest_conversations.save(conversation)  # row lock on the conversation, uncommitted

    async def ingest_cancels_the_idle_row() -> None:
        # What `ScheduleConversationResetUseCase.reconcile` does at the end of an inbound turn.
        await ingest_actions.transition_status(
            ACTION, from_status="scheduled", to_status="cancelled"
        )
        await ingest_actions.save(
            ScheduledAction(
                id="idle-2",
                conversation_id=ConversationId(value=CONVERSATION),
                pending_action_id=None,
                action_type=CONVERSATION_IDLE_RESET_ACTION,
                status="scheduled",
                scheduled_for=datetime.now(UTC) + timedelta(hours=3),
                idempotency_key=IdempotencyKey(value="conversation_idle_reset:idle-2"),
                attempts=0,
            )
        )
        await ingest_session.commit()

    async def ingest_after_the_tick_claimed_the_row() -> None:
        for _ in range(100):  # the tick's claim shows up as a lock on the idle row
            await asyncio.sleep(0.1)
            claimed = (
                await db_session.execute(
                    text(
                        "select count(*) from pg_locks l join pg_stat_activity a using (pid) "
                        "where l.locktype = 'transactionid' and not l.granted"
                    )
                )
            ).scalar_one()
            await db_session.rollback()
            if claimed:
                break
        await ingest_cancels_the_idle_row()

    tick = asyncio.create_task(_run_one_production_tick())
    ingest = asyncio.create_task(ingest_after_the_tick_claimed_the_row())
    try:
        done, pending = await asyncio.wait(
            {tick, ingest}, timeout=TICK_TIMEOUT_SECONDS, return_when=asyncio.ALL_COMPLETED
        )
        if pending:
            blocking = (
                await db_session.execute(
                    text(
                        "select pid, pg_blocking_pids(pid) as blocked_by, state, wait_event_type, "
                        "left(query, 90) as query from pg_stat_activity "
                        "where datname = current_database() and pid <> pg_backend_pid() "
                        "order by pid"
                    )
                )
            ).all()
            for task in pending:
                task.cancel()
            pytest.fail(
                "idle cleanup self-deadlock: the tick did not finish within "
                f"{TICK_TIMEOUT_SECONDS}s; sessions (pid, blocked_by, state, wait, query): "
                f"{[tuple(row) for row in blocking]}"
            )
        # Whoever Postgres picked as the deadlock victim may raise; hanging is the only failure.
        for task in done:
            if not task.cancelled():
                task.exception()
    finally:
        for task in (tick, ingest):
            task.cancel()
        await asyncio.gather(tick, ingest, return_exceptions=True)
        await ingest_session.close()


class _FakeRedisLock:
    async def acquire(self) -> bool:
        return True

    async def release(self) -> None:
        return None


class _FakeRedis:
    def lock(self, *args: object, **kwargs: object) -> _FakeRedisLock:
        return _FakeRedisLock()


async def test_human_mode_lazy_timeout_rotation_does_not_wait_on_its_own_ingest_transaction(
    production_session_factory, db_session
):
    """Ingest saves the conversation (row locked until commit) and then rotates the
    workflow generation. That rotation must reuse the ingest transaction."""
    phone = PhoneNumber("+5491100000088")
    db_session.add(ContactModel(id="contact-human", phone=str(phone)))
    await db_session.flush()
    db_session.add(
        ConversationModel(
            id=f"ycloud-{phone}",
            contact_id="contact-human",
            mode="human",
            last_human_reply_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await db_session.commit()

    ingest = IngestMessageUseCase(
        repositories_provider=open_sqlalchemy_message_repositories,
        debounce_tracker=AsyncMock(),
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        agent_invoker=AsyncMock(),
        runtime_config_service=AsyncMock(),
        send_reply=AsyncMock(),
        workflow_session_repositories_provider=open_sqlalchemy_workflow_session_repositories,
    )
    ingest._schedule_processing = AsyncMock()  # type: ignore[method-assign]

    await asyncio.wait_for(
        ingest.execute(
            InboundMessageDTO(
                external_message_id="wamid.human-timeout", from_phone=phone, text="hola"
            )
        ),
        timeout=TICK_TIMEOUT_SECONDS,
    )

    row = (
        await db_session.execute(
            text("select mode, workflow_session_generation from conversations where id = :id"),
            {"id": f"ycloud-{phone}"},
        )
    ).one()
    assert row.mode == "agent"
