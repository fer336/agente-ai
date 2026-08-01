from dataclasses import dataclass


@dataclass
class ApprovedContent:
    """Minimal approved content shell, sized to type gateway Protocol signatures."""

    id: str
    category: str
    title: str
    body: str
    keywords: list[str]
