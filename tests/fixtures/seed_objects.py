"""Shared seed-object builders for domain objects commonly needed in tests.

Plain factory functions (not `@pytest.fixture`s) — fakes and domain objects
have no setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline helpers these replace.
"""

from datetime import UTC, datetime

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.entities.message import Message
from app.domain.entities.patient import Patient
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber


def make_slot(
    id_: str = "slot-1",
    professional_id: str = "prof-1",
    specialty_id: str = "cleaning",
    start: datetime = datetime(2026, 8, 1, 10, 0),
    end: datetime = datetime(2026, 8, 1, 10, 30),
) -> AppointmentSlot:
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id=specialty_id,
        time_range=DateTimeRange(start, end),
    )


def make_patient(
    id_: str = "pat-1",
    full_name: str = "Jane Doe",
    phone: str = "+5491122334455",
) -> Patient:
    return Patient(id=id_, full_name=full_name, phone=PhoneNumber(phone))


def make_appointment(
    id_: str = "appt-1",
    patient_id: str = "pat-1",
    slot: AppointmentSlot | None = None,
    status: str = "confirmed",
) -> Appointment:
    return Appointment(
        id=AppointmentId(id_),
        patient_id=patient_id,
        slot=slot if slot is not None else make_slot(),
        status=status,
    )


def make_conversation_id(value: str = "conv-1") -> ConversationId:
    return ConversationId(value)


def make_contact(
    id_: str = "contact-1",
    phone: str = "+5491122334455",
    patient_id: str | None = None,
) -> Contact:
    return Contact(id=id_, phone=PhoneNumber(phone), patient_id=patient_id)


def make_conversation(
    id_: str = "chatwoot-100",
    contact_id: str = "contact-1",
    mode: str = "agent",
    created_at: datetime | None = None,
) -> Conversation:
    return Conversation(
        id=ConversationId(id_),
        contact_id=contact_id,
        mode=mode,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def make_message(
    id_: str = "msg-1",
    conversation_id: str = "chatwoot-100",
    external_message_id: str = "wamid.1",
    direction: str = "inbound",
    text: str = "hola",
    created_at: datetime | None = None,
) -> Message:
    return Message(
        id=id_,
        conversation_id=ConversationId(conversation_id),
        external_message_id=ExternalMessageId(external_message_id),
        direction=direction,
        text=text,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )


def make_chatwoot_payload(**overrides: object) -> dict[str, object]:
    """Raw Chatwoot `message_created` webhook JSON body, valid-by-default.

    Callers override individual keys to build the filtered-out/malformed
    variants exercised by the webhook route and payload-parsing tests, e.g.
    `make_chatwoot_payload(message_type="outgoing")`.
    """
    payload: dict[str, object] = {
        "event": "message_created",
        "message_type": "incoming",
        "private": False,
        "source_id": "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5",
        "content": "Hola, quiero agendar un turno",
        "inbox": {"id": 42},
        "sender": {"phone_number": "+5491122334455"},
        "conversation": {"id": 100},
    }
    payload.update(overrides)
    return payload
