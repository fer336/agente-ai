from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocationRequest:
    """A WhatsApp native location message — renders as a map pin the
    patient can tap to open Maps directly, instead of a plain text link.
    `address` is optional (WhatsApp shows it as a subtitle under `name`
    when given).
    """

    latitude: float
    longitude: float
    name: str
    address: str | None = None
