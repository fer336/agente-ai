from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import compile_graph
from app.application.appointments.schedule_follow_up import (
    APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
    APPOINTMENT_FLOW_FOLLOW_UP_RESET,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from app.workers.follow_up_worker import run_follow_up_tick
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_contact_repository,
    make_conversation_repository,
    make_error_service,
    make_message_repository,
    make_node_execution_repository,
    make_proposal_repositories_provider,
    make_scheduled_action_repository,
    make_send_reply_use_case,
    make_specialty_gateway,
    make_tool_execution_repository,
    make_ycloud_messaging_gateway,
)
from tests.fixtures.seed_objects import (
    make_contact,
    make_conversation,
    make_message,
    make_specialty,
)
from tests.fixtures.seed_objects import make_scheduled_action as _make_scheduled_action

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _seed_conversation(conversation_repository, contact_repository, conversation_id="conv-1"):
    async def _seed():
        await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
        await conversation_repository.save(
            make_conversation(id_=conversation_id, contact_id="contact-1", mode="agent")
        )

    return _seed()


@pytest.mark.asyncio
async def test_a_due_prompt_sends_a_message_and_chains_a_reset():
    scheduled_action_repository = make_scheduled_action_repository()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    message_repository = make_message_repository()
    await _seed_conversation(conversation_repository, contact_repository)
    await message_repository.save(
        make_message(
            id_="msg-out",
            conversation_id="conv-1",
            direction="outbound",
            created_at=_NOW - timedelta(minutes=20),
        )
    )
    await scheduled_action_repository.save(
        _make_scheduled_action(
            id_="sa-prompt",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
            status="scheduled",
            scheduled_for=_NOW - timedelta(seconds=5),
        )
    )
    messaging_gateway = make_ycloud_messaging_gateway()
    send_reply = make_send_reply_use_case(messaging_gateway=messaging_gateway)

    count = await run_follow_up_tick(
        scheduled_action_repository=scheduled_action_repository,
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        send_reply=send_reply,
        checkpointer=MemorySaver(),
        now=_NOW,
        limit=50,
        reset_delay_seconds=1200,
    )

    assert count == 1
    assert len(messaging_gateway.sent_messages) == 1
    prompt = await scheduled_action_repository.get_by_id("sa-prompt")
    assert prompt is not None
    assert prompt.status == "executed"
    scheduled = await scheduled_action_repository.get_scheduled_by_conversation_id("conv-1")
    assert len(scheduled) == 1
    assert scheduled[0].action_type == APPOINTMENT_FLOW_FOLLOW_UP_RESET
    assert scheduled[0].scheduled_for == _NOW + timedelta(seconds=1200)
    outbound = [
        m
        for m in await message_repository.get_by_conversation_id_after(
            ConversationId("conv-1"), None
        )
        if m.direction == "outbound" and m.id != "msg-out"
    ]
    assert len(outbound) == 1


@pytest.mark.asyncio
async def test_a_due_prompt_is_cancelled_without_sending_when_the_patient_already_replied():
    scheduled_action_repository = make_scheduled_action_repository()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    message_repository = make_message_repository()
    await _seed_conversation(conversation_repository, contact_repository)
    await message_repository.save(
        make_message(
            id_="msg-in",
            conversation_id="conv-1",
            direction="inbound",
            created_at=_NOW - timedelta(minutes=1),
        )
    )
    await scheduled_action_repository.save(
        _make_scheduled_action(
            id_="sa-prompt",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
            status="scheduled",
            scheduled_for=_NOW - timedelta(seconds=5),
        )
    )
    messaging_gateway = make_ycloud_messaging_gateway()

    count = await run_follow_up_tick(
        scheduled_action_repository=scheduled_action_repository,
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        checkpointer=MemorySaver(),
        now=_NOW,
        limit=50,
        reset_delay_seconds=1200,
    )

    assert count == 1
    assert messaging_gateway.sent_messages == []
    prompt = await scheduled_action_repository.get_by_id("sa-prompt")
    assert prompt is not None
    assert prompt.status == "cancelled"
    assert await scheduled_action_repository.get_scheduled_by_conversation_id("conv-1") == []


@pytest.mark.asyncio
async def test_a_due_reset_clears_the_tramite_and_sends_a_reset_message():
    scheduled_action_repository = make_scheduled_action_repository()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    message_repository = make_message_repository()
    await _seed_conversation(conversation_repository, contact_repository)
    await message_repository.save(
        make_message(
            id_="msg-out",
            conversation_id="conv-1",
            direction="outbound",
            created_at=_NOW - timedelta(minutes=20),
        )
    )
    await scheduled_action_repository.save(
        _make_scheduled_action(
            id_="sa-reset",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_RESET,
            status="scheduled",
            scheduled_for=_NOW - timedelta(seconds=5),
        )
    )
    checkpointer = MemorySaver()
    compiled_graph = compile_graph(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=FakeAgreementGateway(),
        specialty_gateway=make_specialty_gateway(specialties=[make_specialty(id_="cleaning")]),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversation_repository,
        patient_gateway=FakePatientGateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "conv-1"}}
    # A real turn — "Quiero un turno" reaches the numbered specialty list
    # (awaiting_specialty_selection), a genuinely non-terminal stage —
    # rather than hand-assembling a checkpoint the graph never actually
    # wrote (`aupdate_state` on a MULTI-node graph can't infer which node
    # "wrote" an arbitrary external value, unlike the single-node reset
    # graph this worker itself uses).
    seed_result = await compiled_graph.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="Quiero un turno"), config=config
    )
    assert seed_result["collected_data"].get("stage") is not None
    messaging_gateway = make_ycloud_messaging_gateway()

    count = await run_follow_up_tick(
        scheduled_action_repository=scheduled_action_repository,
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        checkpointer=checkpointer,
        now=_NOW,
        limit=50,
        reset_delay_seconds=1200,
    )

    assert count == 1
    assert len(messaging_gateway.sent_messages) == 1
    snapshot = await compiled_graph.aget_state(config)
    assert snapshot.values["collected_data"] == {}
    reset_action = await scheduled_action_repository.get_by_id("sa-reset")
    assert reset_action is not None
    assert reset_action.status == "executed"


@pytest.mark.asyncio
async def test_never_claims_an_unrelated_scheduled_action_type():
    scheduled_action_repository = make_scheduled_action_repository()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    message_repository = make_message_repository()
    await scheduled_action_repository.save(
        _make_scheduled_action(
            id_="sa-confirmation",
            conversation_id="conv-1",
            pending_action_id="pa-1",
            action_type="appointment_confirmation_timeout",
            status="scheduled",
            scheduled_for=_NOW - timedelta(seconds=5),
        )
    )

    count = await run_follow_up_tick(
        scheduled_action_repository=scheduled_action_repository,
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        send_reply=make_send_reply_use_case(),
        checkpointer=MemorySaver(),
        now=_NOW,
        limit=50,
        reset_delay_seconds=1200,
    )

    assert count == 0
    confirmation = await scheduled_action_repository.get_by_id("sa-confirmation")
    assert confirmation is not None
    assert confirmation.status == "scheduled"


class _LosesTheRaceRepository:
    """Wraps a real fake repository, forcing its FIRST `transition_status`
    call to report a loss — simulates another tick/process claiming the
    same row between this tick's `get_due` read and its own claim attempt
    (PRD.md §16.3/§75.9: "Dos workers -> una sola ejecución")."""

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._claim_attempted = False

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    async def transition_status(self, scheduled_action_id, *, from_status, to_status):
        if not self._claim_attempted:
            self._claim_attempted = True
            return False
        return await self._wrapped.transition_status(
            scheduled_action_id, from_status=from_status, to_status=to_status
        )


@pytest.mark.asyncio
async def test_skips_a_row_another_tick_already_claimed():
    real_repository = make_scheduled_action_repository()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    message_repository = make_message_repository()
    await real_repository.save(
        _make_scheduled_action(
            id_="sa-prompt",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
            status="scheduled",
            scheduled_for=_NOW - timedelta(seconds=5),
        )
    )
    messaging_gateway = make_ycloud_messaging_gateway()

    count = await run_follow_up_tick(
        scheduled_action_repository=_LosesTheRaceRepository(real_repository),
        message_repository=message_repository,
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        checkpointer=MemorySaver(),
        now=_NOW,
        limit=50,
        reset_delay_seconds=1200,
    )

    assert count == 0
    assert messaging_gateway.sent_messages == []
    # Untouched by THIS tick — the winning tick (not simulated here) owns
    # whatever status it moved the row to.
    still_there = await real_repository.get_by_id("sa-prompt")
    assert still_there is not None
    assert still_there.status == "scheduled"
