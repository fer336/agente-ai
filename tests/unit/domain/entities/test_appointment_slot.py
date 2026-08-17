from datetime import UTC, datetime

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange


def _time_range() -> DateTimeRange:
    return DateTimeRange(
        start=datetime(2026, 8, 4, 15, 30, tzinfo=UTC),
        end=datetime(2026, 8, 4, 16, 0, tzinfo=UTC),
    )


def test_creates_appointment_slot_with_professional_specialty_and_time_range():
    slot = AppointmentSlot(
        id="slot-1",
        professional_id="prof-9",
        specialty_id="cleaning",
        time_range=_time_range(),
    )

    assert slot.id == "slot-1"
    assert slot.professional_id == "prof-9"
    assert slot.specialty_id == "cleaning"
    assert slot.time_range == _time_range()


def test_appointment_slots_with_different_time_ranges_are_not_equal():
    other_range = DateTimeRange(
        start=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        end=datetime(2026, 8, 5, 9, 30, tzinfo=UTC),
    )
    first = AppointmentSlot(
        id="slot-2", professional_id="prof-1", specialty_id="checkup", time_range=_time_range()
    )
    second = AppointmentSlot(
        id="slot-2", professional_id="prof-1", specialty_id="checkup", time_range=other_range
    )

    assert first != second
