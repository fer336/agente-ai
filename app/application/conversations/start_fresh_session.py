import logging
from typing import Literal

from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber

logger = logging.getLogger(__name__)

StartFreshSessionOutcome = Literal[
    "rotated",
    "contact_not_found",
    "conversation_not_found",
    "contact_mismatch",
    "not_agent_mode",
    "rotation_lost",
]


class StartFreshSessionUseCase:
    """Gives a patient a fresh agent session without deleting any history.

    Rotates the conversation's workflow session generation and clears the
    contact's compacted memory. Messages, checkpoints and agent runs are kept.
    Conversations handed to a human keep their context, and memory is only
    cleared when this call won the rotation CAS.
    """

    def __init__(
        self,
        contacts: ContactRepository,
        conversations: ConversationRepository,
        memory_service: MemoryService,
    ) -> None:
        self._contacts = contacts
        self._conversations = conversations
        self._memory_service = memory_service
        self._rotate = RotateWorkflowSessionUseCase(conversations)

    async def execute(self, phone: PhoneNumber) -> StartFreshSessionOutcome:
        contact = await self._contacts.get_by_phone(phone)
        if contact is None:
            return "contact_not_found"
        # Same id convention as inbound ingestion: YCloud conversations are 1:1 with the phone.
        conversation = await self._conversations.get_by_id(ConversationId(f"ycloud-{phone}"))
        if conversation is None:
            return "conversation_not_found"
        if conversation.contact_id != contact.id:
            return "contact_mismatch"
        if conversation.mode != "agent":
            return "not_agent_mode"
        rotated = await self._rotate.execute(
            conversation.id, expected_generation=conversation.workflow_session_generation
        )
        if not rotated:
            return "rotation_lost"
        await self._memory_service.reset(contact.id)
        logger.info("start_fresh_session.rotated contact_id=%s", contact.id)
        return "rotated"
