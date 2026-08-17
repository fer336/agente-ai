from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import compile_graph
from app.agent.nodes.appointment import OPERATION_CREATE_PAYLOAD
from app.domain.entities.agent_run import COMPLETED, FAILED, HANDOFF
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.agent.langgraph_agent_invoker import (
    AgentRepositories,
    LangGraphAgentInvoker,
)
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_agreement_gateway,
    make_contact_repository,
    make_conversation_repository,
    make_dentalink_gateway,
    make_error_service,
    make_llm_provider,
    make_node_execution_repository,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_send_reply_use_case,
    make_tool_execution_repository,
    make_trace_repositories_provider,
    make_ycloud_handoff_gateway,
    make_ycloud_messaging_gateway,
)
from tests.fixtures.seed_objects import (
    make_agreement,
    make_contact,
    make_conversation,
    make_patient,
)


def _future_slot(id_: str = "slot-1") -> AppointmentSlot:
    now = datetime.now(UTC)
    start = now + timedelta(days=1)
    return AppointmentSlot(
        id=id_,
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


def _make_checkpointer_provider(checkpointer):
    async def provider():
        return checkpointer

    return provider


def _make_invoker(
    conversation_repository=None,
    contact_repository=None,
    messaging_gateway=None,
    handoff_gateway=None,
    agreement_gateway=None,
    appointment_gateway=None,
    patient_gateway=None,
    llm_provider=None,
    proposal_repositories_provider=None,
    trace_repositories_provider=None,
    checkpointer=None,
):
    conversation_repository = conversation_repository or make_conversation_repository()
    contact_repository = contact_repository or make_contact_repository()
    messaging_gateway = messaging_gateway or make_ycloud_messaging_gateway()
    appointment_gateway = appointment_gateway or make_dentalink_gateway()
    checkpointer = MemorySaver() if checkpointer is None else checkpointer

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AgentRepositories]:
        yield AgentRepositories(conversations=conversation_repository, contacts=contact_repository)

    invoker = LangGraphAgentInvoker(
        appointment_gateway=appointment_gateway,
        agreement_gateway=agreement_gateway or make_agreement_gateway(),
        handoff_gateway=handoff_gateway or make_ycloud_handoff_gateway(),
        llm_provider=llm_provider or make_llm_provider(),
        repositories_provider=repositories_provider,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        patient_gateway=patient_gateway or make_patient_gateway(),
        proposal_repositories_provider=(
            proposal_repositories_provider or make_proposal_repositories_provider()
        ),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        trace_repositories_provider=(
            trace_repositories_provider or make_trace_repositories_provider()
        ),
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        alert_threshold_count=5,
        alert_window_seconds=120,
        checkpointer_provider=_make_checkpointer_provider(checkpointer),
    )
    return (
        invoker,
        conversation_repository,
        contact_repository,
        messaging_gateway,
        appointment_gateway,
    )


@pytest.mark.asyncio
async def test_handle_sends_the_graphs_response_to_the_contacts_phone():
    invoker, conversation_repository, contact_repository, messaging_gateway, _ = _make_invoker(
        agreement_gateway=make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    assert len(messaging_gateway.sent_messages) == 1
    phone, text = messaging_gateway.sent_messages[0]
    assert phone == PhoneNumber("+5491122334455")
    assert "OSDE" in text


@pytest.mark.asyncio
async def test_handle_works_without_a_checkpointer_provider():
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    messaging_gateway = make_ycloud_messaging_gateway()
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AgentRepositories]:
        yield AgentRepositories(conversations=conversation_repository, contacts=contact_repository)

    invoker = LangGraphAgentInvoker(
        appointment_gateway=make_dentalink_gateway(),
        agreement_gateway=make_agreement_gateway(agreements=[make_agreement(name="OSDE")]),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=make_llm_provider(),
        repositories_provider=repositories_provider,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        trace_repositories_provider=make_trace_repositories_provider(),
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        alert_threshold_count=5,
        alert_window_seconds=120,
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    assert len(messaging_gateway.sent_messages) == 1


@pytest.mark.asyncio
async def test_handle_sends_nothing_when_conversation_is_already_human():
    invoker, conversation_repository, contact_repository, messaging_gateway, _ = _make_invoker()
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="human")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "hola", None)

    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_handle_sends_nothing_when_conversation_does_not_exist():
    invoker, _, _, messaging_gateway, _ = _make_invoker()

    await invoker.handle(ConversationId("conv-missing"), ["msg-1"], "hola", None)

    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_handle_sends_nothing_when_contact_does_not_exist():
    invoker, conversation_repository, _, messaging_gateway, _ = _make_invoker()
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="missing-contact", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "hola", None)

    assert messaging_gateway.sent_messages == []


@pytest.mark.asyncio
async def test_handle_runs_the_handoff_flow_end_to_end():
    invoker, conversation_repository, contact_repository, messaging_gateway, _ = _make_invoker(
        handoff_gateway=make_ycloud_handoff_gateway()
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(
        ConversationId("conv-1"), ["msg-1"], "Necesito hablar con una persona", None
    )

    assert len(messaging_gateway.sent_messages) == 1
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.mode == "human"


@pytest.mark.asyncio
async def test_handle_carries_collected_data_across_turns_via_the_checkpointer():
    # Explicit carry-over, not implicit LangGraph partial-merge (see the
    # invoker's own docstring): turn 1 shows the operation menu, turn 2
    # (tapping "Sacar turno") asks for identification, turn 3 identifies
    # the patient and stores `collected_data.available_slots`, turn 4 (a
    # stray free-text message instead of a button tap) must still see
    # those same slots to re-offer them — proving the checkpointer
    # actually carried `collected_data` across four separate `handle()`
    # calls, not just within a single graph run.
    checkpointer = MemorySaver()
    slot = _future_slot()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    patient_gateway = make_patient_gateway(
        patients=[make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")]
    )
    invoker, _, _, _, _ = _make_invoker(
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        appointment_gateway=make_dentalink_gateway(available_slots=[slot]),
        patient_gateway=patient_gateway,
        checkpointer=checkpointer,
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "Quiero un turno", None)
    await invoker.handle(
        ConversationId("conv-1"), ["msg-2"], "Sacar turno", OPERATION_CREATE_PAYLOAD
    )
    await invoker.handle(ConversationId("conv-1"), ["msg-3"], "Juan Perez, 30123456", None)
    await invoker.handle(ConversationId("conv-1"), ["msg-4"], "no entiendo", None)

    compiled_graph = compile_graph(
        appointment_gateway=make_dentalink_gateway(available_slots=[slot]),
        agreement_gateway=make_agreement_gateway(),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=make_llm_provider(),
        conversation_repository=conversation_repository,
        patient_gateway=patient_gateway,
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-verify",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=checkpointer,
    )
    snapshot = await compiled_graph.aget_state({"configurable": {"thread_id": "conv-1"}})

    assert snapshot.values["collected_data"]["available_slots"] == [slot]


@pytest.mark.asyncio
async def test_handle_records_an_agent_run_with_a_terminal_status():
    agent_run_repository = make_agent_run_repository()
    trace_repositories_provider = make_trace_repositories_provider(
        agent_runs=agent_run_repository
    )
    invoker, conversation_repository, contact_repository, _, _ = _make_invoker(
        agreement_gateway=make_agreement_gateway(agreements=[make_agreement(name="OSDE")]),
        trace_repositories_provider=trace_repositories_provider,
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    agent_runs = agent_run_repository.all()
    assert len(agent_runs) == 1
    agent_run = agent_runs[0]
    assert agent_run.status == COMPLETED
    assert agent_run.conversation_id == ConversationId("conv-1")
    assert agent_run.message_id == "msg-1"
    assert agent_run.finished_at is not None
    assert agent_run.current_node == "agreement"


@pytest.mark.asyncio
async def test_handle_records_an_agent_run_with_handoff_status():
    agent_run_repository = make_agent_run_repository()
    trace_repositories_provider = make_trace_repositories_provider(
        agent_runs=agent_run_repository
    )
    invoker, conversation_repository, contact_repository, _, _ = _make_invoker(
        trace_repositories_provider=trace_repositories_provider,
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(
        ConversationId("conv-1"), ["msg-1"], "Necesito hablar con una persona", None
    )

    agent_runs = agent_run_repository.all()
    assert len(agent_runs) == 1
    assert agent_runs[0].status == HANDOFF


@pytest.mark.asyncio
async def test_handle_records_an_agent_run_with_failed_status_when_a_node_raises():
    class _BrokenLLMProvider:
        async def classify_intent(self, message, context):
            raise RuntimeError("boom")

    agent_run_repository = make_agent_run_repository()
    trace_repositories_provider = make_trace_repositories_provider(
        agent_runs=agent_run_repository
    )
    invoker, conversation_repository, contact_repository, messaging_gateway, _ = _make_invoker(
        llm_provider=_BrokenLLMProvider(),
        trace_repositories_provider=trace_repositories_provider,
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "hola", None)

    agent_runs = agent_run_repository.all()
    assert len(agent_runs) == 1
    assert agent_runs[0].status == FAILED
    # The graph's own `handle_error` safe fallback still went out — a
    # failed `AgentRun` is an observability signal, not a user-facing one.
    assert len(messaging_gateway.sent_messages) == 1
