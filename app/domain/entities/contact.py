from dataclasses import dataclass

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass
class Contact:
    """Minimal contact shell, sized to type gateway Protocol signatures."""

    id: str
    phone: PhoneNumber
    patient_id: str | None
