from app.domain.value_objects.conversation_id import ConversationId


class FakeAgentInvoker:
    """In-memory fake implementing `AgentInvoker` for local dev and tests.

    Records every call instead of raising, so unit tests can assert on
    exactly what `IngestMessageUseCase` handed off to the Etapa 5 seam.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[ConversationId, list[str], str]] = []

    async def handle(
        self, conversation_id: ConversationId, message_ids: list[str], user_message: str
    ) -> None:
        self.calls.append((conversation_id, message_ids, user_message))
