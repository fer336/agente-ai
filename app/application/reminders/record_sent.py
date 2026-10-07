"""Keep the conversation context of a delivered reminder.

A reminder template is sent outside any conversation. Without this record the
recipient has no contact, no conversation and no message history, so a reply
would start from the welcome menu with no memory of what was asked.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.application.conversations.ensure_conversation import (
    resolve_or_create_contact,
    resolve_or_create_conversation,
)
from app.application.reminders.sent_message_text import render_reminder_text
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.entities.message import ROLE_ASSISTANT, Message
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import TemplateMessage
from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber


class RecordReminderSentUseCase:
    """Ensures the recipient's contact and conversation and stores the sent text.

    Deliberately leaves `workflow_last_activity_at` and the idle-reset timer
    alone: both measure the patient's own activity, and a reminder is not one.
    Safe to repeat: delivery is not exactly-once, and the stored message is
    keyed by the reminder id.
    """

    def __init__(
        self,
        contacts: ContactRepository,
        conversations: ConversationRepository,
        messages: MessageRepository,
    ) -> None:
        self._contacts = contacts
        self._conversations = conversations
        self._messages = messages

    async def execute(
        self, reminder: AppointmentReminder, phone: PhoneNumber, template: TemplateMessage
    ) -> None:
        contact = await resolve_or_create_contact(self._contacts, phone)
        conversation, _ = await resolve_or_create_conversation(
            self._conversations, phone, contact.id
        )
        external_id = ExternalMessageId(f"reminder-{reminder.id}")
        if await self._messages.exists_by_external_id(external_id):
            return
        await self._messages.save(
            Message(
                id=str(uuid4()),
                conversation_id=conversation.id,
                external_message_id=external_id,
                direction="outbound",
                text=render_reminder_text(template),
                created_at=datetime.now(UTC),
                role=ROLE_ASSISTANT,
            )
        )
