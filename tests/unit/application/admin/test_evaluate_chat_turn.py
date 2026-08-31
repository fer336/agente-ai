from datetime import UTC, datetime

import pytest

from app.application.admin.evaluate_chat_turn import (
    EVAL_CONTACT_ID,
    EvaluateChatTurnUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.agent.fake_agent_invoker import FakeAgentInvoker
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_contact_repository,
    make_conversation_repository,
    make_message_repository,
    make_node_execution_repository,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_agent_run, make_node_execution, make_tool_execution

_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


def _use_case(agent_runs=None, node_executions=None, tool_executions=None, messaging_gateway=None):
    return EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=agent_runs or make_agent_run_repository(),
        node_executions=node_executions or make_node_execution_repository(),
        tool_executions=tool_executions or make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=messaging_gateway or FakeYCloudMessagingGateway(),
    )


@pytest.mark.asyncio
async def test_execute_creates_the_eval_contact_and_conversation_and_saves_the_inbound_message():
    conversations = make_conversation_repository()
    contacts = make_contact_repository()
    messages = make_message_repository()
    use_case = EvaluateChatTurnUseCase(
        conversations=conversations,
        contacts=contacts,
        messages=messages,
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "Cancelame el turno de mañana", now=_NOW)

    assert await contacts.get_by_id(EVAL_CONTACT_ID) is not None
    conversation = await conversations.get_by_id(ConversationId("eval-001"))
    assert conversation is not None
    assert conversation.contact_id == EVAL_CONTACT_ID
    saved_messages = await messages.get_by_conversation_id(ConversationId("eval-001"))
    assert [m.text for m in saved_messages] == ["Cancelame el turno de mañana"]


@pytest.mark.asyncio
async def test_execute_reuses_an_existing_conversation_without_duplicating_the_contact():
    conversations = make_conversation_repository()
    contacts = make_contact_repository()
    use_case = EvaluateChatTurnUseCase(
        conversations=conversations,
        contacts=contacts,
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "primer turno", now=_NOW)
    await use_case.execute(ConversationId("eval-001"), "segundo turno", now=_NOW)

    conversation = await conversations.get_by_id(ConversationId("eval-001"))
    assert conversation is not None


@pytest.mark.asyncio
async def test_execute_calls_the_agent_invoker_with_the_saved_message_id():
    invoker = FakeAgentInvoker()
    use_case = EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=invoker,
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "quiero un turno", now=_NOW)

    assert len(invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = invoker.calls[0]
    assert conversation_id == ConversationId("eval-001")
    assert len(message_ids) == 1
    assert user_message == "quiero un turno"
    assert button_payload is None


@pytest.mark.asyncio
async def test_execute_returns_the_latest_agent_run_trace_and_the_last_sent_reply():
    agent_runs = make_agent_run_repository()
    node_executions = make_node_execution_repository()
    tool_executions = make_tool_execution_repository()
    messaging_gateway = FakeYCloudMessagingGateway()

    # Simulates what a real `LangGraphAgentInvoker.handle()` run would have
    # left behind — `FakeAgentInvoker` itself is a no-op recorder.
    await agent_runs.save(make_agent_run(id_="run-1", conversation_id="eval-001"))
    await node_executions.save(make_node_execution(id_="ne-1", agent_run_id="run-1"))
    await tool_executions.save(make_tool_execution(id_="te-1", agent_run_id="run-1"))
    await messaging_gateway.send_text_message(
        PhoneNumber("+5490000000000"), "¿Qué horario preferís?"
    )

    use_case = _use_case(agent_runs, node_executions, tool_executions, messaging_gateway)

    result = await use_case.execute(ConversationId("eval-001"), "quiero un turno", now=_NOW)

    assert result.reply_text == "¿Qué horario preferís?"
    assert result.agent_run is not None
    assert result.agent_run.id == "run-1"
    assert [ne.id for ne in result.node_executions] == ["ne-1"]
    assert [te.id for te in result.tool_executions] == ["te-1"]


@pytest.mark.asyncio
async def test_execute_returns_no_reply_and_empty_trace_when_the_invoker_produced_nothing():
    use_case = _use_case()

    result = await use_case.execute(ConversationId("eval-002"), "hola", now=_NOW)

    assert result.reply_text is None
    assert result.agent_run is None
    assert result.node_executions == []
    assert result.tool_executions == []
