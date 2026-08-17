from app.domain.value_objects.conversation_id import ConversationId


class FakeYCloudHandoffGateway:
    """In-memory fake implementing `HumanHandoffGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.handoff_requests: list[tuple[ConversationId, str]] = []

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None:
        self.handoff_requests.append((conversation_id, reason))
