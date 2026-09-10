from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import compile_graph
from app.agent.nodes.appointment import OPERATION_CREATE_PAYLOAD
from app.application.errors.error_types import YCLOUD_SEND_FAILURE
from app.domain.entities.agent_run import COMPLETED, FAILED, HANDOFF
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.contact_memory import ContactMemory
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.agent.langgraph_agent_invoker import (
    AgentRepositories,
    LangGraphAgentInvoker,
)
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_agreement_gateway,
    make_contact_memory_repository,
    make_contact_repository,
    make_conversation_repository,
    make_dentalink_gateway,
    make_error_repository,
    make_error_service,
    make_linear_gateway,
    make_llm_provider,
    make_message_repository,
    make_node_execution_repository,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_send_reply_use_case,
    make_specialty_gateway,
    make_telegram_notifier,
    make_tool_execution_repository,
    make_trace_repositories_provider,
    make_ycloud_handoff_gateway,
    make_ycloud_messaging_gateway,
)
from tests.fixtures.seed_objects import (
    make_agreement,
    make_contact,
    make_conversation,
    make_message,
    make_patient,
    make_professional,
    make_specialty,
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
    message_repository=None,
    contact_memory_repository=None,
    messaging_gateway=None,
    handoff_gateway=None,
    agreement_gateway=None,
    specialty_gateway=None,
    appointment_gateway=None,
    patient_gateway=None,
    llm_provider=None,
    proposal_repositories_provider=None,
    trace_repositories_provider=None,
    checkpointer=None,
):
    conversation_repository = conversation_repository or make_conversation_repository()
    contact_repository = contact_repository or make_contact_repository()
    message_repository = message_repository or make_message_repository()
    contact_memory_repository = contact_memory_repository or make_contact_memory_repository()
    messaging_gateway = messaging_gateway or make_ycloud_messaging_gateway()
    appointment_gateway = appointment_gateway or make_dentalink_gateway()
    checkpointer = MemorySaver() if checkpointer is None else checkpointer

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AgentRepositories]:
        yield AgentRepositories(
            conversations=conversation_repository,
            contacts=contact_repository,
            messages=message_repository,
            contact_memories=contact_memory_repository,
        )

    invoker = LangGraphAgentInvoker(
        appointment_gateway=appointment_gateway,
        agreement_gateway=agreement_gateway or make_agreement_gateway(),
        specialty_gateway=specialty_gateway or make_specialty_gateway(),
        handoff_gateway=handoff_gateway or make_ycloud_handoff_gateway(),
        llm_provider=llm_provider or make_llm_provider(),
        repositories_provider=repositories_provider,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        patient_gateway=patient_gateway or make_patient_gateway(),
        proposal_repositories_provider=(
            proposal_repositories_provider or make_proposal_repositories_provider()
        ),
        memory_recent_window_size=15,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        trace_repositories_provider=(
            trace_repositories_provider or make_trace_repositories_provider()
        ),
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        alert_threshold_count=5,
        alert_window_seconds=120,
        telegram_notifier=make_telegram_notifier(),
        linear_gateway=make_linear_gateway(),
        incident_threshold_count=10,
        incident_threshold_window_seconds=300,
        telegram_alert_cooldown_seconds=900,
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
async def test_a_send_reply_failure_is_reported_instead_of_left_unobserved():
    # Regression, seen live: a YCloud `ReadTimeout` while sending the final
    # reply propagated all the way up to the fire-and-forget task in
    # `IngestMessageUseCase._debounce_and_process()` with nothing catching
    # it — no `ErrorRecord`, no Telegram alert, nothing but a raw asyncio
    # "Task exception was never retrieved" line. `send_reply.execute()` runs
    # AFTER `compiled_graph.ainvoke()` returns, so every node's own
    # `TraceContext` is already torn down and `MessagingGateway`'s own
    # `traced_call` sees no ambient context to report through.
    class _FailingMessagingGateway(FakeYCloudMessagingGateway):
        async def send_text_message(self, to, text):
            raise TimeoutError("boom")

    errors = make_error_repository()
    invoker, conversation_repository, contact_repository, _, _ = _make_invoker(
        messaging_gateway=_FailingMessagingGateway(),
        trace_repositories_provider=make_trace_repositories_provider(errors=errors),
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    recorded = await errors.list_recent()
    assert len(recorded) == 1
    assert recorded[0].source == "ycloud"
    assert recorded[0].error_type == YCLOUD_SEND_FAILURE
    assert recorded[0].conversation_id == ConversationId("conv-1")


@pytest.mark.asyncio
async def test_handle_populates_agent_state_with_the_contacts_memory_context():
    # Proves `MemoryService.build_agent_context` is actually wired into
    # `handle()` before `graph.ainvoke()` — not just constructible. The
    # checkpointed state is the only externally observable place this
    # shows up, since no node reads these two fields yet.
    checkpointer = MemorySaver()
    message_repository = make_message_repository()
    contact_memory_repository = make_contact_memory_repository()
    await message_repository.save(
        make_message(
            id_="msg-old-1",
            conversation_id="conv-1",
            external_message_id="wamid.old-1",
            text="hola, soy Juan",
        )
    )
    await contact_memory_repository.save(
        ContactMemory(
            id="mem-1",
            contact_id="contact-1",
            summary="Paciente frecuente, prefiere turnos por la tarde.",
            last_compacted_message_id=None,
            last_compacted_at=None,
            updated_at=datetime.now(UTC),
        )
    )
    invoker, conversation_repository, contact_repository, _, _ = _make_invoker(
        message_repository=message_repository,
        contact_memory_repository=contact_memory_repository,
        checkpointer=checkpointer,
    )
    await contact_repository.save(make_contact(id_="contact-1", phone="+5491122334455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    compiled_graph = compile_graph(
        appointment_gateway=make_dentalink_gateway(),
        agreement_gateway=make_agreement_gateway(),
        specialty_gateway=make_specialty_gateway(),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=make_llm_provider(),
        conversation_repository=conversation_repository,
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-verify",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=checkpointer,
    )
    snapshot = await compiled_graph.aget_state({"configurable": {"thread_id": "conv-1:session:1"}})

    assert snapshot.values["recent_messages"] == [{"role": "user", "content": "hola, soy Juan"}]
    assert (
        snapshot.values["contact_memory_summary"]
        == "Paciente frecuente, prefiere turnos por la tarde."
    )


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
        yield AgentRepositories(
            conversations=conversation_repository,
            contacts=contact_repository,
            messages=make_message_repository(),
            contact_memories=make_contact_memory_repository(),
        )

    invoker = LangGraphAgentInvoker(
        appointment_gateway=make_dentalink_gateway(),
        agreement_gateway=make_agreement_gateway(agreements=[make_agreement(name="OSDE")]),
        specialty_gateway=make_specialty_gateway(),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=make_llm_provider(),
        repositories_provider=repositories_provider,
        send_reply=make_send_reply_use_case(messaging_gateway=messaging_gateway),
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        memory_recent_window_size=15,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        trace_repositories_provider=make_trace_repositories_provider(),
        prompt_version="agent-system-v0.1.0",
        model="gpt-4o-mini",
        alert_threshold_count=5,
        alert_window_seconds=120,
        telegram_notifier=make_telegram_notifier(),
        linear_gateway=make_linear_gateway(),
        incident_threshold_count=10,
        incident_threshold_window_seconds=300,
        telegram_alert_cooldown_seconds=900,
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
    # (tapping "Sacar turno") lists the specialties, turn 3 picks one and
    # lists its professionals, turn 4 picks a professional and stores
    # `collected_data.available_slots` — proving the checkpointer actually
    # carried `collected_data` across four separate `handle()` calls, not
    # just within a single graph run.
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
        appointment_gateway=make_dentalink_gateway(
            available_slots=[slot], professionals=[make_professional(id_="prof-1")]
        ),
        patient_gateway=patient_gateway,
        specialty_gateway=make_specialty_gateway(specialties=[make_specialty(id_="cleaning")]),
        checkpointer=checkpointer,
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "Quiero un turno", None)
    await invoker.handle(
        ConversationId("conv-1"), ["msg-2"], "Sacar turno", OPERATION_CREATE_PAYLOAD
    )
    await invoker.handle(ConversationId("conv-1"), ["msg-3"], "1", None)
    await invoker.handle(ConversationId("conv-1"), ["msg-4"], "1", None)

    compiled_graph = compile_graph(
        appointment_gateway=make_dentalink_gateway(available_slots=[slot]),
        agreement_gateway=make_agreement_gateway(),
        specialty_gateway=make_specialty_gateway(),
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
    snapshot = await compiled_graph.aget_state({"configurable": {"thread_id": "conv-1:session:1"}})

    assert snapshot.values["collected_data"]["available_slots"] == [slot]


@pytest.mark.asyncio
async def test_handle_records_an_agent_run_with_a_terminal_status():
    agent_run_repository = make_agent_run_repository()
    trace_repositories_provider = make_trace_repositories_provider(agent_runs=agent_run_repository)
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
    trace_repositories_provider = make_trace_repositories_provider(agent_runs=agent_run_repository)
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
    trace_repositories_provider = make_trace_repositories_provider(agent_runs=agent_run_repository)
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


@pytest.mark.asyncio
async def test_handle_seeds_the_fresh_restart_flag_when_the_conversation_await_one():
    # After a /bot reactivation the conversation row carries
    # `awaiting_fresh_restart=True`. The invoker must seed the flag into
    # the graph state AND consume it (write it back as False) so the
    # welcome menu is rendered exactly once, on the next turn only.
    checkpointer = MemorySaver()
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact(id_="contact-1", phone="+54922224455"))
    reactivated = make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    reactivated.awaiting_fresh_restart = True
    await conversation_repository.save(reactivated)

    invoker, _, _, messaging_gateway, _ = _make_invoker(
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
        checkpointer=checkpointer,
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "hola", None)

    # The reply the patient received is the canonical welcome text, not an
    # LLM free-form continuation. A list reply carries its body text inside
    # `send_list` (see `SendReplyUseCase`), so there is no separate
    # `sent_messages` entry for this turn.
    assert len(messaging_gateway.sent_lists) == 1
    list_to, list_text, list_message = messaging_gateway.sent_lists[0]
    assert list_to == PhoneNumber("+54922224455")
    assert list_text.startswith("Hola! 👋 Bienvenido/a a *Smiling Pilar* 🦷")
    assert [row.id for row in list_message.rows] == [
        "OPERATION_CREATE",
        "OPERATION_RESCHEDULE",
        "OPERATION_CANCEL",
        "MENU_SPECIALTIES",
        "MENU_LOCATION",
        "MENU_ADMIN",
        "OPERATION_VIEW",
    ]
    # Consumed: the flag is back to False so the menu renders once.
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.awaiting_fresh_restart is False

    # And the checkpointed state carried the flag into the graph (the
    # fresh_restart node consumed it within the run).
    snapshot = await compile_graph(
        appointment_gateway=make_dentalink_gateway(),
        agreement_gateway=make_agreement_gateway(),
        specialty_gateway=make_specialty_gateway(),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=make_llm_provider(),
        conversation_repository=conversation_repository,
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-verify",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=checkpointer,
    ).aget_state({"configurable": {"thread_id": "conv-1:session:1"}})
    assert snapshot.values["collected_data"].get("fresh_restart") is None


@pytest.mark.asyncio
async def test_handle_does_not_seed_fresh_restart_when_the_flag_is_absent():
    conversation_repository = make_conversation_repository()
    contact_repository = make_contact_repository()
    await contact_repository.save(make_contact(id_="contact-1", phone="+54922224455"))
    await conversation_repository.save(
        make_conversation(id_="conv-1", contact_id="contact-1", mode="agent")
    )
    invoker, _, _, messaging_gateway, _ = _make_invoker(
        conversation_repository=conversation_repository,
        contact_repository=contact_repository,
    )

    await invoker.handle(ConversationId("conv-1"), ["msg-1"], "¿Trabajan con OSDE?", None)

    # Normal turn: no welcome list was forced.
    assert messaging_gateway.sent_lists == []
    assert len(messaging_gateway.sent_messages) == 1
