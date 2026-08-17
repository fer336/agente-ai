from typing import Protocol, runtime_checkable

from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber


@runtime_checkable
class AppointmentGateway(Protocol):
    """Port to the external appointment scheduling system (e.g. Dentalink)."""

    async def search_availability(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
    ) -> list[AppointmentSlot]: ...

    async def list_professionals(self, specialty_id: str | None = None) -> list[Professional]: ...

    async def get_patient_appointments(self, patient_id: str) -> list[Appointment]: ...

    async def create_appointment(
        self,
        patient: Patient,
        slot: AppointmentSlot,
        idempotency_key: str,
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


@runtime_checkable
class PatientGateway(Protocol):
    """Port to the external patient identification system (e.g. Dentalink).

    PRD.md §32: identification for sensitive operations (viewing/cancelling/
    rescheduling appointments) requires validating full name + DNI against
    this gateway — the phone number alone is never sufficient proof.
    """

    async def find_patient(self, full_name: str, dni: str) -> Patient | None: ...


@runtime_checkable
class AgreementGateway(Protocol):
    """Port to the external insurance/agreement (obra social) catalog (e.g. Dentalink)."""

    async def list_agreements(self) -> list[Agreement]: ...

    async def find_agreement_by_name(self, name: str) -> Agreement | None: ...

    async def get_patient_agreements(self, patient_id: str) -> list[Agreement]: ...


@runtime_checkable
class MessagingGateway(Protocol):
    """Port to the outbound messaging channel (e.g. YCloud/WhatsApp)."""

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        """Sends a text message and returns the external_message_id."""
        ...

    async def send_buttons(
        self, to: PhoneNumber, text: str, buttons: list[InteractiveButton]
    ) -> str:
        """Sends an interactive button message and returns the external_message_id."""
        ...


@runtime_checkable
class HumanHandoffGateway(Protocol):
    """Port to the human-in-the-loop escalation channel (e.g. YCloud Shared Team Inbox)."""

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None: ...
