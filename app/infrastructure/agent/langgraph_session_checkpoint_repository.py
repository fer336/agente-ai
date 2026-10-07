from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.domain.value_objects.conversation_id import ConversationId


class LangGraphSessionCheckpointRepository:
    """`SessionCheckpointRepository` over a LangGraph checkpointer.

    Uses the checkpointer's own `adelete_thread`, which removes one EXACT
    `thread_id` (no LIKE/wildcard), so `conv-1` can never match `conv-10`.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver[Any]) -> None:
        self._checkpointer = checkpointer

    async def delete_generations(
        self, conversation_id: ConversationId, up_to_generation: int
    ) -> None:
        for generation in range(1, up_to_generation + 1):
            await self._checkpointer.adelete_thread(f"{conversation_id}:session:{generation}")
