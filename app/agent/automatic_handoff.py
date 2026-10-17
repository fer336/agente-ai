"""PRD.md §22 automatic-handoff phrases, matched deterministically before the LLM intent.

The patient announcing a delay or a problem with an appointment is never something the
agent tries to fix (PRD.md §22): it always hands off. Relying on the classifier alone let
the real model read "voy a llegar tarde" as an appointment request, so the unambiguous
phrases are matched here on accent-free, case-free, punctuation-free text. Urgencies and
complaints hand off too, and asking for a human always wins.
"""

import re

from app.agent.handoff_offer import normalize_text

#: Wanting a human always wins, wherever the phrase sits in the message.
_HUMAN_REQUEST = re.compile(
    r"\bhablar\s+con\s+(?:una\s+persona|alguien|administracion|un\s+asesor|una\s+asesora|"
    r"asesor|asesora|un\s+humano)\b"
)

#: Appointment problems and delays; a delay only counts unless negated or a purpose.
_APPOINTMENT_PROBLEM = re.compile(
    r"\b(?:"
    r"llego\s+tarde+"
    r"|llegar\s+tarde+"
    r"|no\s+(?:me\s+)?aparece\s+(?:mi|el)\s+turno"
    r"|me\s+equivoque\s+(?:con|de|en)\s+(?:mi|el)\s+turno"
    r"|tengo\s+un\s+problema\s+con\s+(?:mi|el)\s+turno"
    r")\b"
)

#: A negation only cancels a delay when it directly governs the verb: "no llego tarde", "no voy
#: a llegar tarde", "no quiero llegar tarde", "para no llegar tarde", "sin llegar tarde",
#: "evitar llegar tarde". No free words between them, and it never crosses a clause.
_NEGATED_OR_PURPOSE_DELAY = re.compile(
    r"\b(?:no|sin|evitar|evitando)\s+"
    r"(?:(?:voy|vamos|van|quiero|queremos|quiere|pienso)\s+(?:a\s+)?)?(?:llego|llegar)\s+tarde+\b"
)
#: Clause breaks besides punctuation: a negation never reaches across them.
_CLAUSE_CONNECTOR = re.compile(r"\b(?:pero|y|ya\s+que)\b")

#: Arrival notices are only a notice when the clause is short: "ya llego" inside a long
#: sentence is usually something else.
_ARRIVAL_NOTICE = re.compile(r"\b(?:estoy\s+llegando|ya\s+llego)\b")
_MAX_ARRIVAL_CLAUSE_WORDS = 6

#: Urgencies and complaints (LLM "handoff" covers them too; this works in every stage).
_URGENCY_OR_COMPLAINT = re.compile(
    r"\b(?:urgencia|urgente|mucho\s+dolor|me\s+duele\s+mucho|reclamo|queja|"
    r"estoy\s+muy\s+mal|sangr\w*)\b"
)
_NEGATED_URGENCY = re.compile(
    r"\b(?:no|sin)\s+(?:(?:es|hay|tengo|tiene|con)\s+)?(?:una?\s+|ninguna?\s+|nada\s+de\s+)?"
    r"(?:urgencia|urgente|mucho\s+dolor|reclamo|queja|dolor|sangrado)\b"
)

#: Clearly urgent wording (no LLM): breathing trouble, fainting, a head injury, unbearable
#: pain. Matched on accent-free, case-free text; the conservative wording never fires on an
#: ordinary "me duele una muela".
_EMERGENCY = re.compile(
    r"\b(?:"
    r"no\s+puedo\s+respirar"
    r"|(?:me\s+)?cuesta\s+(?:mucho\s+)?respirar"
    r"|dificultad(?:es)?\s+(?:para|al)\s+respirar"
    r"|me\s+falta\s+(?:el\s+)?(?:aire|aliento)"
    r"|me\s+ahog\w*"
    r"|desmay\w*"
    r"|perd\w*\s+(?:el\s+)?(?:conocimiento|sentido)"
    r"|traumatismo\w*"
    r"|golpe\s+(?:muy\s+)?fuerte\s+en\s+(?:la\s+)?(?:cabeza|cara|mandibula)"
    r"|(?:me\s+)?(?:pegu\w*|golpe\w*)\s+(?:muy\s+)?fuerte\s+(?:en\s+)?(?:la\s+)?cabeza"
    r"|dolor\s+(?:es\s+)?insoportable"
    r"|(?:me\s+duele|duele)\s+(?:de\s+forma\s+|de\s+manera\s+)?insoportable\w*"
    r")\b"
)
#: A denial only cancels the symptom it directly governs ("sin desmayos", "no tengo dolor
#: insoportable"). "no puedo respirar" is never denied: there the "no" is the symptom.
_NEGATED_EMERGENCY = re.compile(
    r"\b(?:no|sin|nunca)\s+(?:(?:tengo|tuve|hay|tiene|me|con)\s+)*(?:ningun\w*\s+)?"
    r"(?:desmay\w*|dolor\s+insoportable|traumatismo\w*|"
    r"dificultad(?:es)?\s+(?:para|al)\s+respirar)\b"
)
_SWELLING = re.compile(
    r"\b(?:cara|cuello|rostro|cachete|mejilla|mandibula|cara)\b.{0,40}?"
    r"\b(?:hinchad\w*|inflamad\w*|hinchazon)\b|\b(?:hinchazon|inflamacion)\b.{0,30}?"
    r"\b(?:cara|cuello|rostro|mejilla)\b"
)
_FEVER = re.compile(r"\b(?:fiebre|febril)\b")
_BLOW = re.compile(r"\b(?:golpe\w*|me\s+pegu\w*|accidente|caida|me\s+cai)\b")
_TOOTH_LOST_OR_MOVED = re.compile(
    r"\bdiente\w*\b.{0,30}?\b(?:cayo|salio|salido|rompio|roto|partio|partido|aflojo|movio|"
    r"quebro|quebrado)\b|\b(?:cayo|salio|rompio|partio|aflojo|quebro)\w*\b.{0,30}?"
    r"\bdiente\w*\b"
)


def _is_emergency(normalized: str) -> bool:
    """Deterministic urgent-wording check over accent-free, case-free text."""
    if _EMERGENCY.search(_NEGATED_EMERGENCY.sub(" ", normalized)):
        return True
    if _SWELLING.search(normalized) and _FEVER.search(normalized):
        return True
    return bool(_BLOW.search(normalized) and _TOOTH_LOST_OR_MOVED.search(normalized))


def requires_automatic_handoff(text: str) -> bool:
    """True when the message is one of PRD.md §22's automatic-handoff phrases, an
    urgency/complaint, or a request for a human."""
    normalized = normalize_text(text)
    if _HUMAN_REQUEST.search(normalized):
        return True
    for clause in re.split(r"[.,;:!?\n]+", text):
        for segment in _CLAUSE_CONNECTOR.split(normalize_text(clause)):
            if _APPOINTMENT_PROBLEM.search(_NEGATED_OR_PURPOSE_DELAY.sub(" ", segment)):
                return True
    if _URGENCY_OR_COMPLAINT.search(_NEGATED_URGENCY.sub(" ", normalized)):
        return True
    if _is_emergency(normalized):
        return True
    for clause in re.split(r"[.,;:!?\n]+", text):
        words = normalize_text(clause).split()
        if len(words) <= _MAX_ARRIVAL_CLAUSE_WORDS and _ARRIVAL_NOTICE.search(" ".join(words)):
            return True
    return False
