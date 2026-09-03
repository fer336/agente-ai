from dataclasses import dataclass


@dataclass
class Specialty:
    """Minimal dental specialty shell, sized to type Protocol signatures (mirrors `Agreement`)."""

    id: str
    name: str
