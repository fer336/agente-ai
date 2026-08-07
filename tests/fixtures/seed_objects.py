"""Shared seed-object builders for domain objects commonly needed in tests.

Plain factory functions (not `@pytest.fixture`s) — fakes and domain objects
have no setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline helpers these replace.
"""

from datetime import datetime

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
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
