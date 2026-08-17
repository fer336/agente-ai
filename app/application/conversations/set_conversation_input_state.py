from app.domain.entities.conversation import Conversation
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId

#: PRD.md §6/§24.2's four valid values.
FREE_INPUT = "FREE_INPUT"
INTERACTIVE_SELECTION = "INTERACTIVE_SELECTION"
SENSITIVE_CONFIRMATION = "SENSITIVE_CONFIRMATION"
HUMAN = "HUMAN"


class SetConversationInputStateUseCase:
    """Coordinates flipping `conversation.input_state` (PRD.md §6, §24.2).

    Distinct from `SetConversationModeUseCase` — see `Conversation`'s own
    docstring for why these are two separate concerns, not one field. When
    `conversation_id` has no existing row yet, raises rather than
    fabricating a `Conversation` with an unknown `contact_id` (same
    defensive stance as `SetConversationModeUseCase`).
    """

    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self._conversation_repository = conversation_repository

    async def execute(self, conversation_id: ConversationId, input_state: str) -> None:
        conversation = await self._conversation_repository.get_by_id(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        updated = Conversation(
            id=conversation.id,
            contact_id=conversation.contact_id,
            mode=conversation.mode,
            created_at=conversation.created_at,
            input_state=input_state,
        )
        await self._conversation_repository.save(updated)
