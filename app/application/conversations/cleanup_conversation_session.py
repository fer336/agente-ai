import logging
from enum import StrEnum

from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.memory.memory_service import MemoryService
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.session_checkpoint_repository import SessionCheckpointRepository
from app.domain.value_objects.conversation_id import ConversationId

logger = logging.getLogger(__name__)


class CleanupOutcome(StrEnum):
    CLEANED = "cleaned"
    SKIPPED_CONVERSATION_MISSING = "skipped_conversation_missing"
    SKIPPED_NOT_AGENT_MODE = "skipped_not_agent_mode"
    SKIPPED_CONTACT_MISSING = "skipped_contact_missing"
    ROTATION_LOST = "rotation_lost"


class CleanupConversationSessionUseCase:
    """Wipes the agent's working memory for ONE conversation: LangGraph
    checkpoints of every session generation, the contact's compacted memory
    (DB + cache) and its pending/scheduled actions.

    Deliberately non-destructive for everything else: messages, agent runs,
    errors, incidents, contacts, conversations, Chatwoot mappings, handoffs,
    outbox and sent messages are never touched (unlike
    `ResetConversationUseCase`, which is an admin-only testing tool).

    Safe next to a live turn: the workflow generation CAS is the admission
    gate. Only its winner deletes anything, and only generations up to the
    one it retired, so a turn already running on a newer generation is never
    affected. Pending/scheduled actions are expired (not deleted) by the
    rotation itself.
    """

    def __init__(
        self,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        rotate_workflow_session: RotateWorkflowSessionUseCase,
        session_checkpoints: SessionCheckpointRepository,
        memory_service: MemoryService,
    ) -> None:
        self._conversations = conversations
        self._contacts = contacts
        self._rotate_workflow_session = rotate_workflow_session
        self._session_checkpoints = session_checkpoints
        self._memory_service = memory_service

    async def execute(self, conversation_id: ConversationId) -> CleanupOutcome:
        conversation = await self._conversations.get_by_id(conversation_id)
        if conversation is None:
            return CleanupOutcome.SKIPPED_CONVERSATION_MISSING
        if conversation.mode != "agent":
            # A human/Chatwoot handoff keeps its context.
            return CleanupOutcome.SKIPPED_NOT_AGENT_MODE
        contact = await self._contacts.get_by_id(conversation.contact_id)
        if contact is None:
            return CleanupOutcome.SKIPPED_CONTACT_MISSING

        # Read BEFORE rotating: some repositories mutate the same object.
        retired_generation = conversation.workflow_session_generation
        rotated = await self._rotate_workflow_session.execute(
            conversation_id,
            expected_generation=retired_generation,
            expire_all_pending_generations=True,
        )
        if not rotated:
            return CleanupOutcome.ROTATION_LOST

        await self._session_checkpoints.delete_generations(conversation_id, retired_generation)
        await self._memory_service.reset(contact.id)
        logger.info(
            "cleanup_conversation_session.cleaned conversation=%s retired_generation=%d",
            conversation_id,
            retired_generation,
        )
        return CleanupOutcome.CLEANED
