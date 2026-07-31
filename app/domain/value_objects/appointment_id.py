from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppointmentId:
    """Unique identifier for an Appointment."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("AppointmentId cannot be empty")

    def __str__(self) -> str:
        return self.value
