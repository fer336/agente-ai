"""Answers "which obras sociales do you work with" from Dentalink's live convenios.

Shared by the agreement node and the first-visit intake, so a general question is
never stored as an obra social name and never answered from model memory.
"""

import re

from app.domain.entities.agreement import Agreement

#: Dentalink's "no insurance" convenio: a patient is particular, not covered.
_NON_INSURANCE_AGREEMENT = "particular"

#: A general "which ones do you work with" question. It must be answered from the
#: clinic's live convenios list, never from the model's memory.
LIST_QUESTION = re.compile(
    r"\b(qué|que|cuál|cual|cuáles|cuales)\b.*\b(obras? sociales?|prepagas?|convenios?)\b"
)


def configured_names(agreements: list[Agreement]) -> list[str]:
    return sorted(
        {
            a.name.strip()
            for a in agreements
            if a.name.strip().casefold() != _NON_INSURANCE_AGREEMENT
        },
        key=str.casefold,
    )


def list_message(names: list[str]) -> str:
    return (
        f"Trabajamos con estas obras sociales y prepagas: {', '.join(names)}. "
        "Si tu obra social no está en la lista, podés atenderte como particular."
    )


def not_found_message(names: list[str]) -> str:
    """Static fallback for an unmatched name: says the clinic does not have that
    convenio and gives the real list, so the patient is not asked to retype."""
    return (
        f"Esa obra social o prepaga no la tenemos en convenio. Trabajamos con: {', '.join(names)}."
    )
