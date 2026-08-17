from datetime import UTC, datetime

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange


def _slot() -> AppointmentSlot:
    return AppointmentSlot(
        id="slot-1",
        professional_id="prof-9",
        specialty_id="cleaning",
        time_range=DateTimeRange(
            start=datetime(2026, 8, 4, 15, 30, tzinfo=UTC),
            end=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
        ),
    )


def test_creates_appointment_with_id_patient_slot_and_status():
    appointment = Appointment(
        id=AppointmentId(value="appt-1"),
        patient_id="patient-1",
        slot=_slot(),
        status="confirmed",
    )

    assert appointment.id == AppointmentId(value="appt-1")
    assert appointment.patient_id == "patient-1"
    assert appointment.slot == _slot()
    assert appointment.status == "confirmed"


def test_appointments_with_different_status_are_not_equal():
    first = Appointment(
        id=AppointmentId(value="appt-2"), patient_id="patient-2", slot=_slot(), status="pending"
    )
    second = Appointment(
        id=AppointmentId(value="appt-2"), patient_id="patient-2", slot=_slot(), status="cancelled"
    )

    assert first != second
