from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InteractiveButton:
    """A single tappable reply button in an interactive WhatsApp message."""

    id: str
    title: str
