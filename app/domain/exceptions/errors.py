class DomainError(Exception):
    """Base class for errors raised by domain business rules."""


class AppointmentSlotUnavailableError(DomainError):
    """Raised when a chosen appointment slot is no longer available."""


class DuplicateMessageError(DomainError):
    """Raised when an inbound message has already been processed."""


class DuplicateActionError(DomainError):
    """Raised when a pending action has already been executed."""


class PatientNotIdentifiedError(DomainError):
    """Raised when a sensitive operation is requested without patient identification."""


class PendingActionExpiredError(DomainError):
    """Raised when a pending action is confirmed after its expiration."""


class InvalidConfirmationError(DomainError):
    """Raised when a confirmation response is ambiguous or does not match a pending action."""
