"""Free-text extraction for the first-visit intake reply.

The patient may answer several intake fields (and the first-visit yes/no) in a
single message.  Fields with a fixed shape (email, DNI, the first-visit answer)
are found deterministically; the free-text ones (full name, obra social, plan)
go through the provider's existing ``extract_information`` capability.  The
extractor only *proposes* values: the intake subgraph validates them.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.domain.repositories.llm_provider import LLMProvider
from app.infrastructure.llm.exceptions import LLMProviderError

_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
#: Plain 7-8 digit DNI or the dotted "30.123.456" spelling.
_DNI_PATTERN = re.compile(r"(?<![\d.])(?:\d{7,8}|\d{2}\.\d{3}\.\d{3})(?![\d.])")
#: "ya soy paciente" is always existing; a bare "soy paciente" only when it is
#: neither negated ("no soy paciente") nor incidental ("soy paciente de OSDE").
_EXISTING_PATIENT_PATTERN = re.compile(
    r"\b(?:ya\s+soy\s+paciente|ya\s+fui|"
    r"(?<!\bno\s)(?<!\bnunca\s)soy\s+paciente(?!\s+de\s+(?!(?:la|esta)\s+cl[ií]nica))|"
    r"ya\s+me\s+at(?:ie|e)nd\w+|"
    r"no\s+es\s+(?:mi|la)\s+primera(?:\s+vez)?|no\s*,?\s*no\s+es\s+(?:mi|la)\s+primera)\b",
    re.IGNORECASE,
)
#: Explicitly negated existing-patient phrases: the patient is not one yet.
_NEGATED_EXISTING_PATTERN = re.compile(
    r"\b(?:(?:todav[ií]a\s+)?no\s+soy\s+paciente(?:\s+todav[ií]a)?|nunca\s+fui)\b",
    re.IGNORECASE,
)
_NEW_PATIENT_PATTERN = re.compile(r"\bprimera\s+vez\b", re.IGNORECASE)
_BARE_NO = frozenset({"no", "nop", "nope"})
_BARE_YES = frozenset({"si", "sí", "sip", "claro", "dale"})

#: Intake field -> name handed to `LLMProvider.extract_information`.
_LLM_FIELD_NAMES = {
    "full_name": "nombre_completo",
    "obra_social": "obra_social",
    "plan": "plan",
}
#: Free-text fields where a lone, unstructured answer is safe to take verbatim
#: when the LLM is unavailable.  A full name is never guessed.
_VERBATIM_FALLBACK_FIELDS = frozenset({"obra_social", "plan"})


@dataclass(frozen=True, slots=True)
class IntakeReply:
    """What one free-text reply contained."""

    details: dict[str, str] = field(default_factory=dict)
    first_visit: Literal["new", "existing"] | None = None


def _first_visit_answer(text: str) -> tuple[Literal["new", "existing"] | None, str]:
    """Return the stated first-visit answer and the text without that phrase."""
    bare = text.strip().strip(".,!¡?¿ ").casefold()
    if bare in _BARE_NO:
        return "existing", ""
    if bare in _BARE_YES:
        return "new", ""
    match = _NEGATED_EXISTING_PATTERN.search(text)
    if match is not None:
        return "new", text[: match.start()] + " " + text[match.end() :]
    match = _EXISTING_PATIENT_PATTERN.search(text)
    if match is not None:
        return "existing", text[: match.start()] + " " + text[match.end() :]
    match = _NEW_PATIENT_PATTERN.search(text)
    if match is not None:
        remainder = re.sub(
            r"\b(?:s[ií]|es\s+mi|es\s+la|mi|la)\b[\s,]*$",
            "",
            text[: match.start()],
            flags=re.IGNORECASE,
        )
        return "new", remainder + " " + text[match.end() :]
    return None, text


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,.;:-")


async def extract_intake_reply(
    llm_provider: LLMProvider, text: str, missing_fields: list[str]
) -> IntakeReply:
    """Extract every still-missing intake field (and the first-visit answer) from ``text``."""
    first_visit, remainder = _first_visit_answer(text)
    details: dict[str, str] = {}

    if "email" in missing_fields:
        match = _EMAIL_PATTERN.search(remainder)
        if match is not None:
            details["email"] = match.group(0).strip(".,;")
            remainder = remainder[: match.start()] + " " + remainder[match.end() :]
    if "dni" in missing_fields:
        match = _DNI_PATTERN.search(remainder)
        if match is not None:
            details["dni"] = match.group(0).replace(".", "")
            remainder = remainder[: match.start()] + " " + remainder[match.end() :]

    remainder = _tidy(remainder)
    free_text_missing = [name for name in _LLM_FIELD_NAMES if name in missing_fields]
    if remainder and free_text_missing:
        details.update(await _extract_free_text(llm_provider, remainder, free_text_missing))
    return IntakeReply(details=details, first_visit=first_visit)


async def _extract_free_text(
    llm_provider: LLMProvider, text: str, fields: list[str]
) -> dict[str, str]:
    try:
        result = await llm_provider.extract_information(
            text, [_LLM_FIELD_NAMES[name] for name in fields]
        )
    except LLMProviderError:
        # A lone answer to a lone free-text question is safe to take as-is;
        # with several candidates (or a name) guessing would misfile data.
        if len(fields) == 1 and fields[0] in _VERBATIM_FALLBACK_FIELDS:
            return {fields[0]: text}
        return {}
    extracted: dict[str, str] = {}
    for name in fields:
        if _LLM_FIELD_NAMES[name] in result.missing_fields:
            continue
        value = result.fields.get(_LLM_FIELD_NAMES[name])
        if value is not None and str(value).strip():
            extracted[name] = str(value).strip()
    return extracted
