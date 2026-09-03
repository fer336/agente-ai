from dataclasses import dataclass

#: Standard Argentine DNI (Documento Nacional de Identidad) digit range.
#: Older DNIs can be 7 digits; current issuance is 8. No check digit exists.
_MIN_DIGITS = 7
_MAX_DIGITS = 8


@dataclass(frozen=True, slots=True)
class Dni:
    """A validated Argentine DNI (Documento Nacional de Identidad).

    Guardrail: every DNI this codebase sends to Dentalink must pass through
    here first — `__post_init__` rejects a malformed value with `ValueError`
    *before* any HTTP call is made. This only validates that the input is a
    well-formed Argentine DNI (7-8 digits, no letters) — there is no check
    digit to verify, unlike a Chilean RUT. Whether Dentalink's own backend
    (a Chilean platform whose `rut` field this value is sent into) actually
    accepts an Argentine-format value is a separate, unverified concern —
    see `app.infrastructure.dentalink.patient_gateway`'s module docstring.

    Accepts common input formats ("30.123.456", "30123456") and normalizes
    to plain digits ("30123456") in `.value`.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = self.value.strip().replace(".", "").replace(" ", "")
        if not cleaned.isdigit():
            raise ValueError(f"Invalid DNI: {self.value!r}")
        if not (_MIN_DIGITS <= len(cleaned) <= _MAX_DIGITS):
            raise ValueError(f"Invalid DNI: {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value
