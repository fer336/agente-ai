"""Deterministic detection of a message that is only a greeting.

A greeting is not out of scope: the patient gets the welcome menu again. The check is strict,
the WHOLE message must be greeting words plus harmless small talk ("Hola, ¿cómo andan?",
"Hola, quiero info"), so anything that also asks for something ("hola, quiero un turno") keeps
its normal routing.
"""

import re

from app.agent.handoff_offer import normalize_text

_REPEATED_LETTERS = re.compile(r"(.)\1+")

#: At least one of these must be present.
_GREETING_WORDS = frozenset(
    {"hola", "ola", "holis", "buenas", "buenos", "buen", "hey", "saludos", "buenisimas"}
)
#: Words that may ride along with a greeting without adding a request.
_SMALL_TALK_WORDS = frozenset(
    {
        "dia",
        "dias",
        "tarde",
        "tardes",
        "noche",
        "noches",
        "como",
        "andan",
        "anda",
        "estan",
        "esta",
        "estas",
        "va",
        "que",
        "tal",
        "todo",
        "bien",
        "quiero",
        "queria",
        "info",
        "informacion",
        "una",
        "consulta",
        "ayuda",
        "necesito",
        "a",
        "todos",
        "todas",
        "equipo",
    }
)


def _collapse(word: str) -> str:
    """Folds elongations ("holaaa", "buenasss") onto the plain spelling."""
    return _REPEATED_LETTERS.sub(r"\1", word)


_GREETINGS = frozenset(_collapse(word) for word in _GREETING_WORDS)
_SMALL_TALK = frozenset(_collapse(word) for word in _SMALL_TALK_WORDS)


def is_greeting(text: str) -> bool:
    """True when the whole message is a greeting, with at most harmless small talk."""
    words = [_collapse(word) for word in normalize_text(text).split()]
    if not words or len(words) > 6:
        return False
    if not any(word in _GREETINGS for word in words):
        return False
    return all(word in _GREETINGS or word in _SMALL_TALK for word in words)
