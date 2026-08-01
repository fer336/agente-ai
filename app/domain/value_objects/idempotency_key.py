from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Unique key guaranteeing a scheduling operation is not repeated."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("IdempotencyKey cannot be empty")

    def __str__(self) -> str:
        return self.value
