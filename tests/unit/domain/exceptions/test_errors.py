import pytest

from app.domain.exceptions.errors import (
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
        AppointmentSlotUnavailableError,
        DuplicateMessageError,
        DuplicateActionError,
        PatientNotIdentifiedError,
        PendingActionExpiredError,
        InvalidConfirmationError,
    ],
)
def test_domain_errors_are_subclasses_of_domain_error(error_class):
    assert issubclass(error_class, DomainError)


def test_domain_error_is_a_plain_exception():
    assert issubclass(DomainError, Exception)
