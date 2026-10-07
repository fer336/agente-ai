from datetime import UTC, datetime

import pytest

from app.application.conversations.ensure_conversation import (
    new_conversation_workflow_generation_seed,
    resolve_or_create_contact,
    resolve_or_create_conversation,
)
from app.domain.entities.contact import Contact
from app.domain.exceptions.errors import ContactAlreadyExistsError, ConversationAlreadyExistsError
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from tests.fixtures.gateways import make_contact_repository, make_conversation_repository
from tests.fixtures.seed_objects import make_conversation

PHONE = PhoneNumber("+5491122334455")


@pytest.mark.asyncio
async def test_creates_a_contact_once_and_reuses_it():
    contacts = make_contact_repository()

    first = await resolve_or_create_contact(contacts, PHONE)
    second = await resolve_or_create_contact(contacts, PHONE)

    assert first.phone == PHONE
    assert first.patient_id is None
    assert second.id == first.id


@pytest.mark.asyncio
async def test_a_contact_creation_race_returns_the_winner():
    winner = Contact(id="contact-winner", phone=PHONE, patient_id=None)

    class Racing(type(make_contact_repository())):
        raced = False

        async def save(self, contact):
            if not self.raced:
                self.raced = True
                await super().save(winner)
                raise ContactAlreadyExistsError(str(contact.phone))
            await super().save(contact)

    assert await resolve_or_create_contact(Racing(), PHONE) == winner


@pytest.mark.asyncio
async def test_creates_an_agent_mode_ycloud_conversation_flagged_as_new_then_reuses_it():
    conversations = make_conversation_repository()

    created, is_new = await resolve_or_create_conversation(conversations, PHONE, "contact-1")
    reused, reused_is_new = await resolve_or_create_conversation(conversations, PHONE, "contact-1")

    assert (created.id, created.mode, created.contact_id) == (
        ConversationId("ycloud-+5491122334455"),
        "agent",
        "contact-1",
    )
    assert created.workflow_session_generation == new_conversation_workflow_generation_seed(
        created.created_at
    )
    assert created.workflow_last_activity_at is None
    assert is_new is True
    assert (reused.id, reused_is_new) == (created.id, False)


@pytest.mark.asyncio
async def test_a_conversation_creation_race_returns_the_winner_as_not_new():
    winner = make_conversation(id_="ycloud-+5491122334455", mode="agent")

    class Racing(type(make_conversation_repository())):
        raced = False

        async def save(self, conversation):
            if not self.raced:
                self.raced = True
                await super().save(winner)
                raise ConversationAlreadyExistsError(str(conversation.id))
            await super().save(conversation)

    conversation, is_new = await resolve_or_create_conversation(Racing(), PHONE, "contact-1")

    assert (conversation, is_new) == (winner, False)


def test_generation_seed_is_the_creation_epoch_second():
    created_at = datetime(2026, 10, 7, 12, tzinfo=UTC)

    assert new_conversation_workflow_generation_seed(created_at) == int(created_at.timestamp())
