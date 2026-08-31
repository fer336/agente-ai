from datetime import UTC, datetime

import pytest

from app.application.admin.conversation_queries import ConversationQueryService
from app.domain.entities.agent_run import COMPLETED, FAILED
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_conversation_repository,
    make_error_repository,
    make_message_repository,
)
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_conversation,
    make_error_record,
    make_message,
)


def _service(conversations=None, messages=None, agent_runs=None, errors=None):
    return ConversationQueryService(
        conversations=conversations or make_conversation_repository(),
        messages=messages or make_message_repository(),
        agent_runs=agent_runs or make_agent_run_repository(),
        errors=errors or make_error_repository(),
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
