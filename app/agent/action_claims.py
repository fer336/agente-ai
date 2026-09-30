"""Deterministic guard: an LLM-worded reply must never claim an action already ran.

Confirming, cancelling and rescheduling only happen when the patient taps the
confirmation button and the gateway call succeeds. Everything the model words before
that (reminders, proposals, free-text answers) must not say or imply otherwise, so this
backstop sits behind the prompt rule ("never trust the prompt alone", PRD.md §75.5).
"""

import re

#: Safe text for a free-text answer (question/fallback nodes) that claimed an action ran.
SAFE_ACTION_CLAIM_ANSWER = (
    "Todavía no se hizo ningún cambio en tus turnos: se confirman o se cancelan solo "
    "tocando los botones ✅ Confirmar / ❌ Cancelar del paso correspondiente."
)

#: First-person present ("te lo confirmo") and past ("ya lo cancelé") of the actions.
_FIRST_PERSON_PRESENT = r"(?:confirmo|cancelo|reprogramo|reservo|agendo|anoto)"
_FIRST_PERSON_PAST = r"(?:confirmé|cancelé|reprogramé|reservé|agendé|anoté)"
_PARTICIPLE = r"(?:confirmad|cancelad|reprogramad|agendad|anotad|reservad)[oa]s?"

_CLAIM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # "te lo confirmo", "te la cancelo", "ahí te lo reprogramo"
        rf"\bte\s+(?:lo|la|los|las)\s+(?:{_FIRST_PERSON_PRESENT}|{_FIRST_PERSON_PAST}"
        r"|dejo\s+" + _PARTICIPLE + r")\b",
        # "te confirmo el turno", "te reservo el de las 10" — but "te confirmo que atendemos"
        # is plain information.
        rf"\bte\s+{_FIRST_PERSON_PRESENT}\b(?!\s+(?:que|si|cu[aá]l|cu[aá]nto|cu[aá]ndo|el\s+dato)\b)",
        # "ya te anoté", "ya lo cancelé", "ya confirmé", "he confirmado"
        rf"\bya\s+(?:te\s+)?(?:(?:lo|la)\s+)?{_FIRST_PERSON_PAST}\b",
        rf"\b{_FIRST_PERSON_PAST}\s+(?:tu|el|ese|su|la)\s+(?:turno|cita|consulta|reserva)\b",
        r"\bhe\s+(?:confirmad|cancelad|reprogramad|agendad|anotad|reservad)o\b",
        # "confirmamos tu turno", "cancelamos el turno"
        r"\b(?:confirmamos|cancelamos|reprogramamos|agendamos|anotamos|reservamos)\s+"
        r"(?:tu|el|ese|su|la)\s+(?:turno|cita|consulta|reserva)\b",
        # "listo, turno confirmado", "Listo! Quedó cancelado"
        rf"\blist[oa]\b[^.!?\n]{{0,40}}\b{_PARTICIPLE}\b",
        # "quedó confirmado", "ya está cancelado", "queda reprogramado"
        rf"\b(?:qued[óo]|queda|quedaron|est[aá]|fue|ya\s+est[aá])\s+(?:ya\s+)?{_PARTICIPLE}\b",
        # "nos vemos el lunes", "te esperamos mañana"
        r"\bnos\s+vemos\s+(?:el|este|esta|la|ma[ñn]ana|hoy|pasado)\b",
        r"\bte\s+esperamos\s+(?:el|este|esta|ma[ñn]ana|hoy|pasado)\b",
    )
)

#: Words that make a claim conditional or negated. "no"/"todavía"/"aún" only count right
#: before the verb ("todavía no está confirmado"); a distant "no" ("No te preocupes, ahí te
#: lo cancelo") must not hide a claim. The others count anywhere earlier in the sentence
#: ("cuando toques Confirmar, queda confirmado").
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|todav[ií]a|a[uú]n)\s+(?:\w+\s+)?$|\bas[ií]\s+$", re.IGNORECASE
)
_CONDITION_BEFORE = re.compile(
    r"\b(?:cuando|una\s+vez|si|apenas|hasta\s+que|para\s+que)\b", re.IGNORECASE
)
_SENTENCE_BREAK = re.compile(r"[.!?\n]")


def _is_hedged(text: str, match_start: int) -> bool:
    sentence_start = 0
    for boundary in _SENTENCE_BREAK.finditer(text, 0, match_start):
        sentence_start = boundary.end()
    prefix = text[sentence_start:match_start]
    return bool(_NEGATION_BEFORE.search(prefix) or _CONDITION_BEFORE.search(prefix))


def claims_executed_action(text: str) -> bool:
    """True when `text` says or implies an appointment action was already carried out.

    Only meant for replies produced while no action ran in the turn; a genuine
    post-execution message must bypass it explicitly rather than be guessed at.
    """
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_hedged(text, match.start()):
                return True
    return False


def guard_free_text_answer(text: str) -> str:
    """Returns `text`, or the safe static answer when it claims an action already ran.

    For the model's free-text answers (`understand()`'s `answer`), which never execute
    anything: a claim there is always false.
    """
    if claims_executed_action(text):
        return SAFE_ACTION_CLAIM_ANSWER
    return text
