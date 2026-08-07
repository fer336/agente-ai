from app.domain.value_objects.conversation_id import ConversationId


class NotImplementedAgentInvoker:
    """DI-wired `AgentInvoker` stub until Etapa 5's LangGraph agent exists.

    Raising loudly here (rather than silently no-op'ing) makes the Etapa 5
    seam impossible to miss once `IngestMessageUseCase` actually reaches it
    in a running environment — the swap point is `get_agent_invoker` in
    `app.api.dependencies.gateways`.
    """

    async def handle(
        self, conversation_id: ConversationId, message_ids: list[str], user_message: str
    ) -> None:
        raise NotImplementedError(
            "AgentInvoker.handle is the Etapa 5 seam — no agent implementation exists yet"
        )
