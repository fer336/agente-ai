from typing import Protocol, runtime_checkable

from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class AgentInvoker(Protocol):
    """Etapa 5 seam: hands a debounced, lock-held, grouped inbound turn to the agent.

    `IngestMessageUseCase` calls `handle()` once the debounce window has
    elapsed and the per-conversation lock is held. `button_payload` carries
    the machine-readable id of a tapped interactive button when the turn's
    last message was a button reply, `None` otherwise (PRD.md §6: a button
    carries a KNOWN intent and must route deterministically, never through
    LLM re-classification of its text).
    """

    async def handle(
        self,
        conversation_id: ConversationId,
        message_ids: list[str],
        user_message: str,
        button_payload: str | None,
    ) -> None: ...
