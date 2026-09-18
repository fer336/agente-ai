from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.application.appointments.schedule_follow_up import APPOINTMENT_FLOW_FOLLOW_UP_RESET
from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
)
from app.domain.entities.message import ROLE_ASSISTANT, Message
from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.idempotency_key import IdempotencyKey
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from app.workers.follow_up_worker import (
    FollowUpWorkerRepositories,
    run_follow_up_loop,
    run_follow_up_tick,
)
from tests.fixtures.gateways import (
    make_contact_repository,
    make_conversation_repository,
    make_message_repository,
    make_send_reply_use_case,
    make_ycloud_messaging_gateway,
)
from tests.fixtures.seed_objects import make_contact, make_conversation


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


def _due_action(
    action_type: str,
    conversation_id: str = "ycloud-+5491122334455",
    id_: str = "action-1",
) -> ScheduledAction:
    return ScheduledAction(
        id=id_,
        conversation_id=ConversationId(conversation_id),
        pending_action_id=None,
        action_type=action_type,
        status="scheduled",
        scheduled_for=datetime.now(UTC) - timedelta(seconds=1),
        idempotency_key=IdempotencyKey(value=f"{action_type}:{id_}"),
        attempts=0,
    )


@pytest.mark.asyncio
async def test_conversation_idle_reset_in_agent_mode_rotates_silently():
    # Revised per the user's own explicit ask: this used to also send the
    # welcome menu proactively — now it ONLY retires the stuck workflow
    # generation server-side, with no message of any kind. The patient
    # only sees a fresh start once they write again.
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(mode="agent"))
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact())
    scheduled_action_repository = FakeScheduledActionRepository()
    await scheduled_action_repository.save(_due_action(CONVERSATION_IDLE_RESET_ACTION))
    message_repository = make_message_repository()
    messaging_gateway = make_ycloud_messaging_gateway()
    send_reply = make_send_reply_use_case(messaging_gateway=messaging_gateway)

    processed = await run_follow_up_tick(
        scheduled_action_repository,
        message_repository,
        conversation_repository,
        contact_repository,
        send_reply,
        None,
        now=datetime.now(UTC),
        limit=50,
        reset_delay_seconds=1200,
    )

    assert processed == 1
    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.workflow_session_generation == 2
    assert messaging_gateway.sent_lists == []
    assert messaging_gateway.sent_messages == []
    assert await message_repository.get_recent_by_conversation_id(
        ConversationId("ycloud-+5491122334455"), limit=10
    ) == []
    action = await scheduled_action_repository.get_by_id("action-1")
    assert action is not None
    assert action.status == "executed"


@pytest.mark.asyncio
async def test_conversation_idle_reset_in_human_mode_sends_nothing():
    # A staff handoff owns its own reactivation timing — the idle reset
    # must never barge into an active mode="human" conversation with the
    # bot's welcome menu.
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(mode="human"))
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact())
    scheduled_action_repository = FakeScheduledActionRepository()
    await scheduled_action_repository.save(_due_action(CONVERSATION_IDLE_RESET_ACTION))
    messaging_gateway = make_ycloud_messaging_gateway()
    send_reply = make_send_reply_use_case(messaging_gateway=messaging_gateway)

    processed = await run_follow_up_tick(
        scheduled_action_repository,
        make_message_repository(),
        conversation_repository,
        contact_repository,
        send_reply,
        None,
        now=datetime.now(UTC),
        limit=50,
        reset_delay_seconds=1200,
    )

    assert processed == 1
    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.workflow_session_generation == 1
    assert messaging_gateway.sent_lists == []
    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_appointment_flow_follow_up_reset_rotates_the_workflow_generation():
    # Regression: this used to call `aupdate_state` against a bare
    # `str(conversation_id)` thread_id, which never matches any real
    # checkpoint row (every real thread_id carries a `:session:N` suffix)
    # — the "reinicié el trámite" message went out, but the stuck stage
    # never actually cleared. Rotating the generation is what actually
    # gives the next turn a fresh, empty thread.
    conversation_repository = make_conversation_repository()
    await conversation_repository.save(make_conversation(mode="agent"))
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact())
    message_repository = make_message_repository()
    await message_repository.save(
        Message(
            id="msg-1",
            conversation_id=ConversationId("ycloud-+5491122334455"),
            external_message_id=ExternalMessageId("wamid.agent-1"),
            direction="outbound",
            text="¿Seguís ahí?",
            created_at=datetime.now(UTC),
            role=ROLE_ASSISTANT,
        )
    )
    scheduled_action_repository = FakeScheduledActionRepository()
    await scheduled_action_repository.save(_due_action(APPOINTMENT_FLOW_FOLLOW_UP_RESET))
    messaging_gateway = make_ycloud_messaging_gateway()
    send_reply = make_send_reply_use_case(messaging_gateway=messaging_gateway)

    await run_follow_up_tick(
        scheduled_action_repository,
        message_repository,
        conversation_repository,
        contact_repository,
        send_reply,
        None,
        now=datetime.now(UTC),
        limit=50,
        reset_delay_seconds=1200,
    )

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.workflow_session_generation == 2
    assert len(messaging_gateway.sent_messages) == 1
