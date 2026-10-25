from datetime import UTC, datetime, timedelta

import pytest

from app.application.admin.conversation_queries import ConversationQueryService
from app.domain.entities.agent_run import COMPLETED, FAILED
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_conversation_repository,
    make_error_repository,
    make_message_repository,
    make_scheduled_action_repository,
)
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_conversation,
    make_error_record,
    make_message,
    make_scheduled_action,
)


def _service(conversations=None, messages=None, agent_runs=None, errors=None, scheduled=None):
    return ConversationQueryService(
        conversations=conversations or make_conversation_repository(),
        messages=messages or make_message_repository(),
        agent_runs=agent_runs or make_agent_run_repository(),
        errors=errors or make_error_repository(),
        scheduled_actions=scheduled or make_scheduled_action_repository(),
    )


@pytest.mark.asyncio
async def test_list_conversations_reports_last_message_latest_run_and_error_count():
    conversations = make_conversation_repository()
    messages = make_message_repository()
    agent_runs = make_agent_run_repository()
    errors = make_error_repository()

    await conversations.save(make_conversation(id_="conv-1", contact_id="contact-9"))
    await messages.save(
        make_message(
            id_="msg-1",
            conversation_id="conv-1",
            text="primero",
            created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        )
    )
    await messages.save(
        make_message(
            id_="msg-2",
            conversation_id="conv-1",
            text="segundo",
            created_at=datetime(2026, 1, 1, 9, 5, tzinfo=UTC),
        )
    )
    await agent_runs.save(make_agent_run(id_="run-1", conversation_id="conv-1", status=COMPLETED))
    await errors.save(make_error_record(id_="err-1", conversation_id="conv-1"))

    service = _service(conversations, messages, agent_runs, errors)
    summaries = await service.list_conversations()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.conversation_id == "conv-1"
    assert summary.patient_or_identifier == "contact-9"
    assert summary.last_message_text == "segundo"
    assert summary.latest_run_status == COMPLETED
    assert summary.error_count == 1


@pytest.mark.asyncio
async def test_list_conversations_handles_a_conversation_with_no_messages_or_runs():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="conv-empty"))

    service = _service(conversations=conversations)
    summaries = await service.list_conversations()

    assert len(summaries) == 1
    assert summaries[0].last_message_text is None
    assert summaries[0].latest_run_status is None
    assert summaries[0].error_count == 0


@pytest.mark.asyncio
async def test_get_conversation_detail_returns_none_when_missing():
    service = _service()

    assert await service.get_conversation_detail(ConversationId("missing")) is None


@pytest.mark.asyncio
async def test_get_conversation_detail_aggregates_messages_runs_and_errors():
    conversations = make_conversation_repository()
    messages = make_message_repository()
    agent_runs = make_agent_run_repository()
    errors = make_error_repository()

    await conversations.save(make_conversation(id_="conv-1"))
    await messages.save(make_message(id_="msg-1", conversation_id="conv-1"))
    await agent_runs.save(make_agent_run(id_="run-1", conversation_id="conv-1", status=FAILED))
    await errors.save(make_error_record(id_="err-1", conversation_id="conv-1"))

    service = _service(conversations, messages, agent_runs, errors)
    detail = await service.get_conversation_detail(ConversationId("conv-1"))

    assert detail is not None
    assert detail.conversation.id == ConversationId("conv-1")
    assert [m.id for m in detail.messages] == ["msg-1"]
    assert [r.id for r in detail.agent_runs] == ["run-1"]
    assert [e.id for e in detail.errors] == ["err-1"]


def _idle_reset(conversation_id: str, at: datetime, **kwargs):
    return make_scheduled_action(
        id_=kwargs.pop("id_", "sa-idle"),
        conversation_id=conversation_id,
        pending_action_id=None,
        action_type="conversation_idle_reset",
        scheduled_for=at,
        idempotency_key=kwargs.pop("idempotency_key", "idle-1"),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_agent_mode_counts_down_to_the_scheduled_idle_cleanup():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="c-1", mode="agent"))
    scheduled = make_scheduled_action_repository()
    due = datetime.now(UTC) + timedelta(hours=2)
    await scheduled.save(_idle_reset("c-1", due))
    service = _service(conversations=conversations, scheduled=scheduled)

    detail = await service.get_conversation_detail(ConversationId("c-1"))
    summaries = await service.list_conversations()

    assert detail is not None
    assert detail.reset_deadline is not None
    assert (detail.reset_deadline.at, detail.reset_deadline.kind) == (due, "idle_cleanup")
    assert summaries[0].reset_deadline == detail.reset_deadline


@pytest.mark.asyncio
async def test_agent_mode_without_a_scheduled_cleanup_has_no_countdown():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="c-1", mode="agent"))
    service = _service(conversations=conversations)

    detail = await service.get_conversation_detail(ConversationId("c-1"))

    assert detail is not None
    assert detail.reset_deadline is None


@pytest.mark.asyncio
async def test_other_scheduled_actions_do_not_drive_the_countdown():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="c-1", mode="agent"))
    scheduled = make_scheduled_action_repository()
    await scheduled.save(make_scheduled_action(id_="sa-other", conversation_id="c-1"))
    service = _service(conversations=conversations, scheduled=scheduled)

    detail = await service.get_conversation_detail(ConversationId("c-1"))

    assert detail is not None
    assert detail.reset_deadline is None


@pytest.mark.asyncio
async def test_a_deferred_cleanup_moves_the_countdown_with_it():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="c-1", mode="agent"))
    scheduled = make_scheduled_action_repository()
    later = datetime.now(UTC) + timedelta(days=1)
    await scheduled.save(_idle_reset("c-1", later))
    service = _service(conversations=conversations, scheduled=scheduled)

    detail = await service.get_conversation_detail(ConversationId("c-1"))

    assert detail is not None
    assert detail.reset_deadline is not None
    assert detail.reset_deadline.at == later


@pytest.mark.asyncio
async def test_human_mode_counts_down_from_the_last_staff_reply():
    conversations = make_conversation_repository()
    replied = datetime.now(UTC) - timedelta(minutes=20)
    await conversations.save(
        make_conversation(id_="c-1", mode="human", last_human_reply_at=replied)
    )
    service = _service(conversations=conversations)

    detail = await service.get_conversation_detail(ConversationId("c-1"))

    assert detail is not None
    assert detail.reset_deadline is not None
    assert detail.reset_deadline.kind == "human_timeout"
    assert detail.reset_deadline.at == replied + timedelta(hours=1)


@pytest.mark.asyncio
async def test_human_mode_without_a_staff_reply_never_expires():
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="c-1", mode="human", last_human_reply_at=None))
    service = _service(conversations=conversations)

    detail = await service.get_conversation_detail(ConversationId("c-1"))

    assert detail is not None
    assert detail.reset_deadline is None
