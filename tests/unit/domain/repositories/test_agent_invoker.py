from app.domain.repositories.agent_invoker import AgentInvoker


class ConformingAgentInvoker:
    async def handle(self, conversation_id, message_ids, user_message):
        return None


class PartialAgentInvoker:
    """Missing `handle` entirely — `runtime_checkable` Protocol conformance
    only checks method presence, not signature arity, so the negative case
    must omit the method rather than narrow its parameters."""


def test_conforming_class_satisfies_agent_invoker_protocol():
    assert isinstance(ConformingAgentInvoker(), AgentInvoker)


def test_partial_class_does_not_satisfy_agent_invoker_protocol():
    assert not isinstance(PartialAgentInvoker(), AgentInvoker)
