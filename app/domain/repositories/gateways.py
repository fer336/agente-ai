from typing import Protocol, runtime_checkable

from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
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
class MessagingGateway(Protocol):
    """Port to the outbound messaging channel (e.g. WhatsApp)."""

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        """Sends a text message and returns the external_message_id."""
        ...


@runtime_checkable
class HumanHandoffGateway(Protocol):
    """Port to the human-in-the-loop escalation channel (e.g. Chatwoot)."""

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None: ...
