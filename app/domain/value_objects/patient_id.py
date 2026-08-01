from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PatientId:
    """Unique identifier for a Patient."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("PatientId cannot be empty")

    def __str__(self) -> str:
        return self.value
