from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationId:
    """Unique identifier for a Conversation."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("ConversationId cannot be empty")

    def __str__(self) -> str:
        return self.value
