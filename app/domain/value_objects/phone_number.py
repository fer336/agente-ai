from dataclasses import dataclass

_MIN_DIGITS = 8
_MAX_DIGITS = 15


@dataclass(frozen=True, slots=True)
class PhoneNumber:
    """A phone number in E.164 format (e.g. +5491122334455)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("+"):
            raise ValueError("PhoneNumber must be in E.164 format, starting with '+'")

        digits = self.value[1:]
        if not digits.isdigit():
            raise ValueError("PhoneNumber must contain only digits after the leading '+'")

        if not (_MIN_DIGITS <= len(digits) <= _MAX_DIGITS):
            raise ValueError(
                f"PhoneNumber must have between {_MIN_DIGITS} and {_MAX_DIGITS} digits"
            )

    def __str__(self) -> str:
        return self.value
