from dataclasses import dataclass


@dataclass
class Professional:
    """Minimal professional (dentist) shell, sized to type gateway Protocol signatures."""

    id: str
    full_name: str
    specialty_id: str | None
