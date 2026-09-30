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
    for clause in re.split(r"[.,;:!?\n]+", text):
        words = normalize_text(clause).split()
        if len(words) <= _MAX_ARRIVAL_CLAUSE_WORDS and _ARRIVAL_NOTICE.search(" ".join(words)):
            return True
    return False
