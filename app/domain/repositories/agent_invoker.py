from typing import Protocol, runtime_checkable

from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class AgentInvoker(Protocol):
    """Etapa 5 seam: hands a debounced, lock-held, grouped inbound turn to the agent.

    `IngestMessageUseCase` calls `handle()` once the debounce window has
    elapsed and the per-conversation lock is held. No LangGraph/agent logic
    exists yet in this etapa — see `app.infrastructure.agent.not_implemented_agent_invoker`
    for the DI-wired stub used until Etapa 5 replaces the binding.
    """

    async def handle(
        self, conversation_id: ConversationId, message_ids: list[str], user_message: str
    ) -> None: ...
