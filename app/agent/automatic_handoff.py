"""PRD.md §22 automatic-handoff phrases, matched deterministically before the LLM intent.

The patient announcing a delay or a problem with an appointment is never something the
agent tries to fix (PRD.md §22): it always hands off. Relying on the classifier alone let
the real model read "voy a llegar tarde" as an appointment request, so the unambiguous
phrases are matched here on accent-free, case-free, punctuation-free text.
"""

import re

from app.agent.handoff_offer import normalize_text

_PHRASE = re.compile(
    r"\b(?:"
    r"llego\s+tarde+"
    r"|llegar\s+tarde+"
    r"|estoy\s+llegando"
    r"|ya\s+llego"
    r"|no\s+(?:me\s+)?aparece\s+(?:mi|el)\s+turno"
    r"|me\s+equivoque\s+(?:con|de|en)\s+(?:mi|el)\s+turno"
    r"|tengo\s+un\s+problema\s+con\s+(?:mi|el)\s+turno"
    r"|hablar\s+con\s+(?:una\s+persona|alguien|administracion|un\s+asesor|una\s+asesora|"
    r"asesor|asesora|un\s+humano)"
    r")\b"
)

#: "no llego tarde" / "no voy a llegar tarde" is the opposite of a delay notice.
_NEGATED_DELAY = re.compile(r"\bno\s+(?:voy\s+a\s+)?(?:llego|llegar)\s+tarde+\b")


def requires_automatic_handoff(text: str) -> bool:
    """True when the message is one of PRD.md §22's automatic-handoff phrases."""
    normalized = normalize_text(text)
    if _NEGATED_DELAY.search(normalized):
        return False
    return _PHRASE.search(normalized) is not None
