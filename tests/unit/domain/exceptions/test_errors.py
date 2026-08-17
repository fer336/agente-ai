import pytest

from app.domain.exceptions.errors import (
    AppointmentNotFoundError,
    AppointmentSlotUnavailableError,
    DomainError,
    DuplicateActionError,
    DuplicateMessageError,
    InvalidConfirmationError,
    PatientNotIdentifiedError,
    PendingActionExpiredError,
)


@pytest.mark.parametrize(
    "error_class",
    [
        DuplicateMessageError,
        DuplicateActionError,
        PatientNotIdentifiedError,
        PendingActionExpiredError,
        InvalidConfirmationError,
        AppointmentNotFoundError,
    ],
)
def test_domain_errors_are_subclasses_of_domain_error(error_class):
    assert issubclass(error_class, DomainError)


def test_domain_error_is_a_plain_exception():
    assert issubclass(DomainError, Exception)


def test_appointment_not_found_error_exposes_appointment_id_attribute():
    exc = AppointmentNotFoundError("999")

    assert exc.appointment_id == "999"
    assert str(exc) == "Appointment 999 not found"


def test_appointment_slot_unavailable_error_exposes_slot_id_attribute():
    exc = AppointmentSlotUnavailableError("slot-1")

    assert exc.slot_id == "slot-1"
    assert issubclass(AppointmentSlotUnavailableError, DomainError)
