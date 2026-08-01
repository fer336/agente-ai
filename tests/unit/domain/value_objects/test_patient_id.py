import dataclasses

import pytest

from app.domain.value_objects.patient_id import PatientId


def test_creates_patient_id_from_non_empty_string():
    patient_id = PatientId(value="patient-123")

    assert patient_id.value == "patient-123"


def test_patient_id_is_frozen():
    patient_id = PatientId(value="patient-123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        patient_id.value = "patient-999"  # type: ignore[misc]


def test_rejects_empty_patient_id():
    with pytest.raises(ValueError, match="empty"):
        PatientId(value="")


def test_rejects_whitespace_only_patient_id():
    with pytest.raises(ValueError, match="empty"):
        PatientId(value="   ")
