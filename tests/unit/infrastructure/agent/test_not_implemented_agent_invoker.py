import pytest

from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.agent.not_implemented_agent_invoker import NotImplementedAgentInvoker


def test_satisfies_agent_invoker_protocol():
    assert isinstance(NotImplementedAgentInvoker(), AgentInvoker)


@pytest.mark.asyncio
async def test_handle_raises_not_implemented_error():
    invoker = NotImplementedAgentInvoker()

    with pytest.raises(NotImplementedError):
        await invoker.handle(ConversationId("conv-1"), ["msg-1"], "hola", None)
