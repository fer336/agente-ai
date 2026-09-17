from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId


class SetConversationModeUseCase:
    """Coordinates flipping `conversation.mode` (PRD.md §21, §23).

    PRD.md §23: "El estado se almacenará en PostgreSQL... YCloud no será la
    única fuente de verdad." When `conversation_id` has no existing row yet
    (shouldn't happen in practice — `IngestMessageUseCase` always creates
    one before the agent ever runs — but handled defensively), this raises
    rather than fabricating a `Conversation` with an unknown `contact_id`.
    """

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self._conversation_repository = conversation_repository

    async def execute(self, conversation_id: ConversationId, mode: str) -> None:
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Mutate in place — see `SetConversationInputStateUseCase`'s own
        # comment for why reconstructing a `Conversation` with a
        # hand-picked field list is the bug this replaces: it silently
        # dropped `workflow_session_generation`/`workflow_last_activity_at`/
        # `awaiting_fresh_restart` back to their dataclass defaults on
        # every mode flip.
        conversation.mode = mode
        await self._conversation_repository.save(conversation)
