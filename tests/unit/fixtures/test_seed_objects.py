from datetime import datetime

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.seed_objects import (
    make_appointment,
    make_conversation_id,
    make_patient,
    make_slot,
)


def test_make_slot_returns_slot_with_sensible_defaults():
    slot = make_slot()

    assert slot == AppointmentSlot(
        id="slot-1",
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=slot.time_range,
    )
    assert slot.time_range.start == datetime(2026, 8, 1, 10, 0)
    assert slot.time_range.end == datetime(2026, 8, 1, 10, 30)


def test_make_slot_applies_keyword_overrides():
    slot = make_slot(id_="slot-2", specialty_id="whitening")

    assert slot.id == "slot-2"
    assert slot.specialty_id == "whitening"
    assert slot.professional_id == "prof-1"


def test_make_patient_returns_patient_with_sensible_defaults():
    patient = make_patient()

    assert patient == Patient(id="pat-1", full_name="Jane Doe", phone=patient.phone)
    assert str(patient.phone) == "+5491122334455"


def test_make_patient_applies_keyword_overrides():
    patient = make_patient(id_="pat-2", full_name="John Roe")

    assert patient.id == "pat-2"
    assert patient.full_name == "John Roe"


def test_make_appointment_returns_confirmed_appointment_with_sensible_defaults():
    appointment = make_appointment()

    assert appointment.patient_id == "pat-1"
    assert appointment.status == "confirmed"
    assert str(appointment.id) == "appt-1"
    assert isinstance(appointment, Appointment)


def test_make_appointment_applies_keyword_overrides():
    slot = make_slot(id_="slot-9")

    appointment = make_appointment(id_="appt-2", patient_id="pat-9", slot=slot, status="cancelled")

    assert str(appointment.id) == "appt-2"
    assert appointment.patient_id == "pat-9"
    assert appointment.slot == slot
    assert appointment.status == "cancelled"


def test_make_conversation_id_returns_conversation_id_with_sensible_default():
    conversation_id = make_conversation_id()

    assert conversation_id == ConversationId("conv-1")


def test_make_conversation_id_applies_value_override():
    conversation_id = make_conversation_id(value="conv-42")

    assert conversation_id == ConversationId("conv-42")
