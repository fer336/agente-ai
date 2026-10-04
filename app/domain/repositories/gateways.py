from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Literal, Protocol, runtime_checkable

from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.entities.treatment import Treatment
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.phone_number import PhoneNumber


@dataclass(frozen=True, slots=True)
class TemplateQuickReplyButton:
    """A template quick-reply button and its deterministic callback payload."""

    index: int
    payload: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("Template quick-reply button index cannot be negative")
        if not self.payload.strip():
            raise ValueError("Template quick-reply button payload cannot be empty")


@dataclass(frozen=True, slots=True)
class TemplateMessage:
    """Vendor-neutral WhatsApp template message.

    Template names and language are configuration-owned; body parameters and
    quick-reply payloads stay structured so the adapter cannot accidentally
    serialize a display label as a callback payload.
    """

    name: str
    language: str
    body_parameters: tuple[str, ...] = ()
    quick_reply_buttons: tuple[TemplateQuickReplyButton, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Template name cannot be empty")
        if not self.language.strip():
            raise ValueError("Template language cannot be empty")


@runtime_checkable
class AppointmentGateway(Protocol):
    """Port to the external appointment scheduling system (e.g. Dentalink)."""

    @property
    def clinic_timezone(self) -> tzinfo:
        """The clinic's own timezone — needed by any caller that must
        align a search window to a CALENDAR day as Dentalink itself
        understands one (`fecha` is a clinic-local calendar date, not a
        UTC one). Exposed on the port itself, not just the real gateway's
        constructor, so an application/agent-layer caller can build a
        clinic-tz-aligned `DateTimeRange` without importing infrastructure
        or `Settings` directly — see `SearchAvailabilityAnyProfessionalUseCase`'s
        caller (`_offer_any_professional_slots`) for the motivating case: a
        UTC-aligned window silently lost a clinic-local slot that fell on
        the next UTC calendar date.
        """
        ...

    async def search_availability(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
        limit: int | None = None,
    ) -> list[AppointmentSlot]:
        """`limit` lets an implementation stop searching early once it has
        enough slots to show. Dentalink's agenda endpoint only accepts a
        single date, so a wide `date_range` costs one HTTP call per day —
        walking all of them after the caller already has what it needs is
        what got this integration rate-limited (429) in production."""
        ...

    async def search_specialty_availability(
        self,
        specialty_id: str,
        date_range: DateTimeRange,
        limit: int,
    ) -> list[AppointmentSlot]:
        """The soonest slots (ascending, deduped by id) of ONE specialty
        inside `date_range`, at most `limit`. The specialty filter is applied
        by the scheduling system itself, so a specialty with few
        professionals is not drowned out by the rest of the branch's agenda;
        an implementation walks forward from the range start with a bounded
        request count instead of querying every day of the range."""
        ...

    async def list_professionals(self, specialty_id: str | None = None) -> list[Professional]: ...

    async def get_patient_appointments(self, patient_id: str) -> list[Appointment]: ...

    async def create_appointment(
        self,
        patient: Patient,
        slot: AppointmentSlot,
        idempotency_key: str,
        comment: str | None = None,
    ) -> Appointment: ...

    async def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot: AppointmentSlot,
        idempotency_key: str,
    ) -> Appointment: ...

    async def cancel_appointment(
        self,
        appointment_id: str,
        idempotency_key: str,
    ) -> None: ...


ReminderAppointmentState = Literal[
    "active", "confirmed", "attended", "cancelled", "no_show", "unknown"
]


@dataclass(frozen=True, slots=True)
class ReminderAppointment:
    """Read model used only to decide whether and when to send a reminder."""

    id: str
    patient_id: str
    starts_at: datetime
    raw_status_id: str
    raw_status_name: str
    state: ReminderAppointmentState


@dataclass(frozen=True, slots=True)
class ReminderPatient:
    """Minimum patient data required for reminder delivery."""

    patient_id: str
    mobile: PhoneNumber


@runtime_checkable
class ReminderAppointmentGateway(Protocol):
    """Read-only appointment port for reminder scheduling."""

    async def list_reminder_appointments_for_date_window(
        self, start_date: date, end_date: date
    ) -> list[ReminderAppointment]: ...


@runtime_checkable
class ReminderPatientGateway(Protocol):
    """Read-only patient contact port for reminder delivery."""

    async def get_reminder_patient(self, patient_id: str) -> ReminderPatient | None: ...


@runtime_checkable
class PatientGateway(Protocol):
    """Port to the external patient identification system (e.g. Dentalink).

    PRD.md §32: identification for sensitive operations (viewing/cancelling/
    rescheduling appointments) requires validating full name + DNI against
    this gateway — the phone number alone is never sufficient proof.
    """

    async def find_patient(self, full_name: str, dni: str) -> Patient | None: ...

    async def find_patient_by_dni(self, dni: str) -> Patient | None:
        """Looks a patient up by DNI alone, with no name check.

        Used to detect an already-registered patient whose typed name does
        not match the record on file, so they are never asked to register
        again (nor to re-enter their data in a loop).
        """
        ...

    async def create_patient(
        self, full_name: str, dni: str, phone: PhoneNumber, email: str | None = None
    ) -> Patient:
        """Creates a new patient, tied to the requesting contact's own `phone`.

        Guardrail (IDOR/contact-isolation): `phone` must always be the
        phone number of the conversation/contact currently being served —
        never a caller-supplied arbitrary patient phone — so every created
        record is provably linked to whoever asked for it. Implementations
        must reject a duplicate RUT (see `PatientAlreadyExistsError`)
        rather than silently creating a second record for the same person.

        `email` is optional and only ever comes from the registration
        Flow — never required for identification (PRD.md §32).
        """
        ...


@runtime_checkable
class AgreementGateway(Protocol):
    """Port to the external insurance/agreement (obra social) catalog (e.g. Dentalink)."""

    async def list_agreements(self) -> list[Agreement]: ...

    async def find_agreement_by_name(self, name: str) -> Agreement | None: ...

    async def get_patient_agreements(self, patient_id: str) -> list[Agreement]: ...

    async def link_patient_agreement(self, patient_id: str, agreement_id: str) -> None:
        """Associates an existing agreement/convenio with a patient.

        Used only by the registration Flow's "Obra Social" field: the
        patient's answer is resolved to a real `Agreement` first (same
        `find_agreement_by_name` catalog match `agreement.py` already
        uses for Q&A), then linked here — Dentalink models convenio
        membership as its own relationship, never a plain field on the
        patient record itself (`POST /pacientes/{id}/convenios`).

        Raises `AgreementAlreadyLinkedError` when the patient already has
        that agreement, so the caller can tell them and carry on.
        """
        ...


@runtime_checkable
class SpecialtyGateway(Protocol):
    """Port to the external dental specialty catalog (e.g. Dentalink)."""

    async def list_specialties(self) -> list[Specialty]: ...


@runtime_checkable
class TreatmentGateway(Protocol):
    """Port to the external treatment-plan catalog (e.g. Dentalink).

    Read-only and always scoped to one already-identified patient — never a
    "list every treatment" call. Matches PRD.md §32's identification
    guardrail already enforced by `PatientGateway`: a treatment plan
    carries billing detail (balance owed, amounts paid), so it is only ever
    fetched for the patient this conversation already proved is who they
    say they are.
    """

    async def get_patient_treatments(self, patient_id: str) -> list[Treatment]: ...


@runtime_checkable
class MessagingGateway(Protocol):
    """Port to the outbound messaging channel (e.g. YCloud/WhatsApp)."""

    async def send_template(self, to: PhoneNumber, template: TemplateMessage) -> str:
        """Sends an approved WhatsApp template and returns its external id."""
        ...

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        """Sends a text message and returns the external_message_id."""
        ...

    async def send_buttons(
        self,
        to: PhoneNumber,
        text: str,
        buttons: list[InteractiveButton],
        image_url: str | None = None,
    ) -> str:
        """Sends an interactive button message and returns the
        external_message_id. `image_url` (a publicly reachable URL — a
        WhatsApp/YCloud recipient's servers fetch it themselves) attaches
        an image header above the body text, e.g. the welcome message's
        clinic logo (this session's brief)."""
        ...

    async def send_flow(self, to: PhoneNumber, text: str, flow: FlowRequest) -> str:
        """Sends a WhatsApp Flow message and returns the external_message_id."""
        ...

    async def send_location(self, to: PhoneNumber, location: LocationRequest) -> str:
        """Sends a native WhatsApp location message and returns the
        external_message_id — a tap opens Maps directly, unlike a plain
        text link."""
        ...

    async def send_list(self, to: PhoneNumber, text: str, list_message: ListMessage) -> str:
        """Sends an interactive list message and returns the
        external_message_id — up to 10 rows, WhatsApp's own cap. A patient
        picks a row, no need for `INTERACTIVE_SELECTION` free-text parsing
        (PRD.md §6): the reply carries a known, deterministic row id."""
        ...

    async def get_contact_phone(self, ycloud_contact_id: str) -> PhoneNumber | None:
        """Resolves a vendor-side contact id to its phone number, or `None`
        if the contact has no known/valid phone. Needed because YCloud's
        `contact.attributes_changed` webhook event carries only the
        contact's opaque id, never its phone number.
        """
        ...

    async def send_typing_indicator(self, wamid: str) -> None:
        """Marks the given inbound message (by its wamid) as read and
        shows a "typing..." indicator to the patient while a reply is
        being prepared.
        """
        ...


@runtime_checkable
class HumanHandoffGateway(Protocol):
    """Port to the human-in-the-loop escalation channel (e.g. YCloud Shared Team Inbox)."""

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None: ...
