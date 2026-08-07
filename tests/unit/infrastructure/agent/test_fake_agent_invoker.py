import pytest

from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.agent.fake_agent_invoker import FakeAgentInvoker


def test_satisfies_agent_invoker_protocol():
    assert isinstance(FakeAgentInvoker(), AgentInvoker)


@pytest.mark.asyncio
async def test_handle_records_the_call():
    invoker = FakeAgentInvoker()
    conversation_id = ConversationId("conv-1")

    await invoker.handle(conversation_id, ["msg-1", "msg-2"], "hola doctor")

    assert invoker.calls == [(conversation_id, ["msg-1", "msg-2"], "hola doctor")]
