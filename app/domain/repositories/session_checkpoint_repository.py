from typing import Protocol, runtime_checkable

from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class SessionCheckpointRepository(Protocol):
    """Port to the agent's per-session graph checkpoints.

    Checkpoint threads are keyed `{conversation_id}:session:{generation}`
    (see `LangGraphAgentInvoker`); this port only ever addresses those exact
    thread ids, never a pattern, so one conversation can never affect another.
    """

    async def delete_generations(
        self, conversation_id: ConversationId, up_to_generation: int
    ) -> None:
        """Deletes the checkpoints of generations `1..up_to_generation`
        (inclusive) of ONE conversation. Idempotent: missing threads are a
        no-op, and a non-positive `up_to_generation` deletes nothing.
        """
        ...
