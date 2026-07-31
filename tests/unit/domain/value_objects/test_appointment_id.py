import dataclasses

import pytest

from app.domain.value_objects.appointment_id import AppointmentId


def test_creates_appointment_id_from_non_empty_string():
    appointment_id = AppointmentId(value="appt-123")

    assert appointment_id.value == "appt-123"


def test_appointment_id_is_frozen():
    appointment_id = AppointmentId(value="appt-123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        appointment_id.value = "appt-999"  # type: ignore[misc]


def test_rejects_empty_appointment_id():
    with pytest.raises(ValueError, match="empty"):
        AppointmentId(value="")


def test_rejects_whitespace_only_appointment_id():
    with pytest.raises(ValueError, match="empty"):
        AppointmentId(value="   ")
