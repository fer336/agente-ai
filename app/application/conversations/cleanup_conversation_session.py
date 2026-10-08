import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.conversations.schedule_conversation_reset import (
    ScheduleConversationResetUseCase,
)
from app.application.memory.memory_service import MemoryService
from app.domain.repositories.appointment_reminder_repository import AppointmentReminderRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.session_checkpoint_repository import SessionCheckpointRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber

logger = logging.getLogger(__name__)


class CleanupOutcome(StrEnum):
    CLEANED = "cleaned"
    SKIPPED_CONVERSATION_MISSING = "skipped_conversation_missing"
    SKIPPED_NOT_AGENT_MODE = "skipped_not_agent_mode"
    SKIPPED_CONTACT_MISSING = "skipped_contact_missing"
    ROTATION_LOST = "rotation_lost"
    SKIPPED_PENDING_REMINDER = "skipped_pending_reminder"


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

    Deferred while the patient has an appointment reminder already sent whose
    appointment has not started: the reminder's answer (a button tap or free
    text) needs the conversation intact. The skipped cleanup is rescheduled for
    the appointment start plus the idle delay, so it is postponed, never lost.
    A reminder is sent at most about a day and a half before its appointment,
    which bounds the deferral.
    """

    def __init__(
        self,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        rotate_workflow_session: RotateWorkflowSessionUseCase,
        session_checkpoints: SessionCheckpointRepository,
        memory_service: MemoryService,
        appointment_reminders: AppointmentReminderRepository | None = None,
        schedule_conversation_reset: ScheduleConversationResetUseCase | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conversations = conversations
        self._contacts = contacts
        self._rotate_workflow_session = rotate_workflow_session
        self._session_checkpoints = session_checkpoints
        self._memory_service = memory_service
        self._appointment_reminders = appointment_reminders
        self._schedule_conversation_reset = schedule_conversation_reset
        self._clock = clock

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
        if await self._defer_for_pending_reminder(conversation_id, contact.phone):
            return CleanupOutcome.SKIPPED_PENDING_REMINDER

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
            "cleanup_conversation_session.cleaned retired_generation=%d", retired_generation
        )
        return CleanupOutcome.CLEANED

    async def _defer_for_pending_reminder(
        self, conversation_id: ConversationId, phone: PhoneNumber
    ) -> bool:
        if self._appointment_reminders is None or self._schedule_conversation_reset is None:
            return False
        appointment_start = await self._appointment_reminders.latest_pending_appointment_start(
            phone, now=self._clock()
        )
        if appointment_start is None:
            return False
        await self._schedule_conversation_reset.defer_after(conversation_id, appointment_start)
        logger.info("cleanup_conversation_session.deferred_pending_reminder")
        return True
