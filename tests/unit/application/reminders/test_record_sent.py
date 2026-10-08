from datetime import UTC, datetime

import pytest

from app.application.reminders.record_sent import RecordReminderSentUseCase
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.entities.message import ROLE_ASSISTANT
from app.domain.repositories.gateways import TemplateMessage, TemplateQuickReplyButton
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from tests.fixtures.gateways import (
    make_contact_repository,
    make_conversation_repository,
    make_message_repository,
)

PHONE = PhoneNumber("+5491112345678")
CONVERSATION_ID = ConversationId("ycloud-+5491112345678")
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def reminder(reminder_id="r-1"):
    return AppointmentReminder(
        reminder_id,
        "apt-1",
        "patient-1",
        "confirm_day_before",
        "sent",
        NOW,
        str(PHONE),
    )


def template():
    return TemplateMessage(
        "recordatorio_turno_confirmar",
        "es_AR",
        ("Sofía", "jueves 8 de octubre", "10:30"),
        (TemplateQuickReplyButton(0, "REMINDER_CONFIRM:apt-1"),),
    )


def build():
    contacts = make_contact_repository()
    conversations = make_conversation_repository()
    messages = make_message_repository()
    return RecordReminderSentUseCase(contacts, conversations, messages), (
        contacts,
        conversations,
        messages,
    )


@pytest.mark.asyncio
async def test_creates_the_contact_and_conversation_and_stores_one_assistant_message():
    use_case, (contacts, conversations, messages) = build()

    await use_case.execute(reminder(), PHONE, template())

    contact = await contacts.get_by_phone(PHONE)
    conversation = await conversations.get_by_id(CONVERSATION_ID)
    stored = await messages.get_by_conversation_id(CONVERSATION_ID)
    assert contact is not None and conversation is not None
    assert (conversation.contact_id, conversation.mode) == (contact.id, "agent")
    assert len(stored) == 1
    assert (stored[0].direction, stored[0].role) == ("outbound", ROLE_ASSISTANT)
    assert "jueves 8 de octubre" in stored[0].text and "10:30" in stored[0].text


@pytest.mark.asyncio
async def test_never_touches_the_idle_timer_state():
    use_case, (_, conversations, _) = build()

    await use_case.execute(reminder(), PHONE, template())

    conversation = await conversations.get_by_id(CONVERSATION_ID)
    assert conversation is not None
    assert conversation.workflow_last_activity_at is None


@pytest.mark.asyncio
async def test_repeating_the_same_reminder_is_idempotent():
    use_case, (contacts, conversations, messages) = build()

    await use_case.execute(reminder(), PHONE, template())
    await use_case.execute(reminder(), PHONE, template())

    assert len(await messages.get_by_conversation_id(CONVERSATION_ID)) == 1
    assert len(contacts._contacts_by_id) == 1
    assert len(conversations._conversations_by_id) == 1


@pytest.mark.asyncio
async def test_a_second_reminder_for_the_same_phone_reuses_the_conversation():
    use_case, (_, conversations, messages) = build()

    await use_case.execute(reminder("r-1"), PHONE, template())
    first = await conversations.get_by_id(CONVERSATION_ID)
    activity = datetime(2026, 10, 7, 9, tzinfo=UTC)
    assert first is not None
    first.workflow_last_activity_at = activity
    await use_case.execute(reminder("r-2"), PHONE, template())

    assert len(await messages.get_by_conversation_id(CONVERSATION_ID)) == 2
    again = await conversations.get_by_id(CONVERSATION_ID)
    assert again is not None and again.workflow_last_activity_at == activity
