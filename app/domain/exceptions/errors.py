class DomainError(Exception):
    """Base class for errors raised by domain business rules."""


class AppointmentSlotUnavailableError(DomainError):
    """Raised when a chosen appointment slot is no longer available.

    PRD.md §11.2: "Ese horario acaba de ocuparse mientras confirmábamos" —
    raised when a lock can't be acquired or revalidation finds the slot
    gone. Callers must never retry the same slot automatically.
    """

    def __init__(self, slot_id: str) -> None:
        self.slot_id = slot_id
        super().__init__(f"Appointment slot {slot_id} is no longer available")


class DuplicateMessageError(DomainError):
    """Raised when an inbound message has already been processed."""


class DuplicateActionError(DomainError):
    """Raised when a pending action has already been executed."""


class PatientNotIdentifiedError(DomainError):
    """Raised when a sensitive operation is requested without patient identification."""


class PendingActionExpiredError(DomainError):
    """Raised when a pending action is confirmed after its expiration.

    PRD.md §16.3: a same-moment confirmation and expiration race must have
    exactly one winner. This is raised when the guarded
    `pending -> confirmed` transition loses that race (the row was no
    longer `pending` by the time it ran).
    """

    def __init__(self, pending_action_id: str) -> None:
        self.pending_action_id = pending_action_id
        super().__init__(f"PendingAction {pending_action_id} is no longer pending")


class InvalidConfirmationError(DomainError):
    """Raised when a confirmation response is ambiguous or does not match a pending action."""

    def __init__(self, pending_action_id: str) -> None:
        self.pending_action_id = pending_action_id
        super().__init__(f"No matching PendingAction {pending_action_id}")


class AppointmentNotFoundError(DomainError):
    """Raised when an appointment id has no matching record."""

    def __init__(self, appointment_id: str) -> None:
        self.appointment_id = appointment_id
        super().__init__(f"Appointment {appointment_id} not found")


class PatientAlreadyExistsError(DomainError):
    """Raised when creating a patient whose RUT already exists in Dentalink.

    Guardrail: `DentalinkPatientGateway.create_patient` always searches by
    RUT first — this is the typed conflict it raises instead of silently
    creating a duplicate patient record.
    """

    def __init__(self, rut: str, existing_patient_id: str) -> None:
        self.rut = rut
        self.existing_patient_id = existing_patient_id
        super().__init__(f"Patient with RUT {rut} already exists (id={existing_patient_id})")


class ConversationAlreadyExistsError(DomainError):
    """Raised when two concurrent webhook deliveries for the same brand-new
    contact both try to create the same conversation row.

    Seen live: `IngestMessageUseCase._resolve_or_create_conversation`'s own
    `get_by_id` -> `save` is a classic check-then-act race — two inbound
    messages arriving close enough together both saw no existing row and
    both tried to `INSERT`, the second one hitting
    `conversations_pkey`'s real UNIQUE constraint
    (`conversation_id` is deterministically `ycloud-{phone}`, so this can
    only ever be the SAME logical conversation, never a genuine collision
    between two different ones). The repository raises this instead of
    letting the raw `IntegrityError` propagate, so the application layer
    can recover by re-reading rather than crashing the whole webhook.
    """

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation {conversation_id} was created concurrently")


class ContactAlreadyExistsError(DomainError):
    """Raised when two concurrent webhook deliveries for the same brand-new
    phone number both try to create a contact row — same race as
    `ConversationAlreadyExistsError`, for `contacts.phone` (see migration
    0017's own docstring for why that column needed a real UNIQUE
    constraint added before this could be raised at all: `id` alone, a
    fresh UUID per attempt, never collides on its own).
    """

    def __init__(self, phone: str) -> None:
        self.phone = phone
        super().__init__(f"Contact with phone {phone} was created concurrently")
