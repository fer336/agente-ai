from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExternalMessageId:
    """Unique identifier assigned by the messaging provider to an inbound message."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("ExternalMessageId cannot be empty")

    def __str__(self) -> str:
        return self.value
