from app.domain.value_objects.conversation_id import ConversationId


class FakeSessionCheckpointRepository:
    """In-memory fake implementing `SessionCheckpointRepository` for tests."""

    def __init__(self, threads: set[str] | None = None) -> None:
        self.threads: set[str] = set(threads or ())
        self.calls: list[tuple[str, int]] = []

    async def delete_generations(
        self, conversation_id: ConversationId, up_to_generation: int
    ) -> None:
        self.calls.append((str(conversation_id), up_to_generation))
        for generation in range(1, up_to_generation + 1):
            self.threads.discard(f"{conversation_id}:session:{generation}")
