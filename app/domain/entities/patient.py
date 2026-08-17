from dataclasses import dataclass

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass
class Patient:
    """Minimal patient shell, sized to type gateway Protocol signatures."""

    id: str
    full_name: str
    phone: PhoneNumber
    #: National id document number (PRD.md §32: "Nombre completo + DNI" is
    #: the suggested minimum identification bar for sensitive operations).
    #: Optional because most existing `Patient` construction sites (e.g.
    #: `AppointmentGateway.create_appointment`'s caller) never identify by
    #: DNI at all.
    dni: str | None = None
