"""Never act on another person's data from a kinship claim (PRD.md §22, audit v0.44.0).

A patient can only manage their own appointments. A message that says it acts for a
relative ("soy familiar de María", "mi mamá tiene turno", "su DNI es ...") is stopped
before any identification, registration, lookup, reschedule or cancellation runs on the
third party's name or DNI. The reply asks for the patient's own data and offers an advisor.

Detection is deterministic and deliberately narrow: a bare "mi mamá" inside a sentence
that does not ask anything about an appointment for her is not a claim.
"""

import re

from app.agent.handoff_offer import normalize_text

_KIN = (
    r"(?:mama|papa|madre|padre|hijo|hija|hijos|esposo|esposa|marido|mujer|hermano|hermana|"
    r"abuelo|abuela|tio|tia|pareja|novio|novia|nene|nena|suegro|suegra|primo|prima)"
)
_ACTION_FOR_SOMEONE = (
    r"(?:cambi|cancel|reprogram|reagend|agend|anot|sac|mov|pas)(?:ale|ala|alo|arle)"
)

_CLAIM = re.compile(
    r"\bfamiliar(?:es)?\s+de\b"
    r"|\ba\s+nombre\s+de\b"
    r"|\bsu\s+dni\b"
    r"|\bdni\s+de\s+(?:mi\s+" + _KIN + r"|ella|el)\b"
    r"|\b(?:para|de)\s+mi\s+" + _KIN + r"\b"
    r"|\bmi\s+" + _KIN + r"\s+(?:tiene|tenia|necesita|quiere|debe|va\s+a)\b"
    # A clitic action verb only counts next to a kin noun ("cancelale el turno a mi hija").
    r"|\b" + _ACTION_FOR_SOMEONE + r"\b[^.?!]{0,40}\b(?:a|para|de)\s+mi\s+" + _KIN + r"\b"
)

#: Static wording, also the fallback when the LLM-built reply fails the guards.
THIRD_PARTY_STATIC_MESSAGE = (
    "Solo puedo ayudarte con tus propios turnos, no con los de otra persona. Si querés, "
    "escribime tu nombre completo y tu DNI, o te conecto con un asesor."
)

THIRD_PARTY_CONTEXT: dict[str, object] = {
    "situacion": (
        "El paciente dijo que quiere gestionar el turno de otra persona (un familiar). "
        "Solo se pueden atender los turnos del propio paciente."
    ),
    "instruccion": (
        "Explicá con calidez que solo podés ayudar con los turnos del propio paciente, "
        "pedile SU nombre completo y SU DNI, y ofrecele conectarlo con un asesor. No pidas ni "
        "repitas datos de la otra persona, no digas que hiciste ni vas a hacer nada con el "
        "turno. Sin saludo, en dos oraciones cortas. Van a aparecer botones debajo."
    ),
}


def claims_to_act_for_someone_else(text: str) -> bool:
    """True when the message says it manages another person's appointment or data."""
    return _CLAIM.search(normalize_text(text)) is not None
