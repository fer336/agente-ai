from dataclasses import dataclass

from app.domain.value_objects.phone_number import PhoneNumber


@dataclass
class Patient:
    """Minimal patient shell, sized to type gateway Protocol signatures."""

    id: str
    full_name: str
    phone: PhoneNumber
