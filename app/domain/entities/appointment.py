from dataclasses import dataclass

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.appointment_id import AppointmentId


@dataclass
class Appointment:
    """Minimal appointment shell, sized to type gateway Protocol signatures."""

    id: AppointmentId
    patient_id: str
    slot: AppointmentSlot
    status: str
