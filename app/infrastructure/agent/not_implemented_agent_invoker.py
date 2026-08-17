from app.domain.value_objects.conversation_id import ConversationId


class NotImplementedAgentInvoker:
    """DI-wired `AgentInvoker` stub, kept as a reference/example implementation.

    No longer bound in production DI (see `app.api.dependencies.gateways.get_agent_invoker`,
    which now returns `LangGraphAgentInvoker`) — retained for anyone building
    a fresh `AgentInvoker` swap point from scratch.
    """

    async def handle(
        self,
        conversation_id: ConversationId,
        message_ids: list[str],
        user_message: str,
        button_payload: str | None,
    ) -> None:
        raise NotImplementedError(
            "AgentInvoker.handle is the Etapa 5 seam — no agent implementation exists yet"
        )
