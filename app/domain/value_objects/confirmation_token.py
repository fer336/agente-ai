from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfirmationToken:
    """Token a patient must reference to confirm a pending action."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("ConfirmationToken cannot be empty")

    def __str__(self) -> str:
        return self.value
