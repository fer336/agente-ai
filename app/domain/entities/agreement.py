from dataclasses import dataclass


@dataclass
class Agreement:
    """Minimal insurance agreement (obra social) shell, sized to type Protocol signatures."""

    id: str
    name: str
