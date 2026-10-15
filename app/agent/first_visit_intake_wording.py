"""Wording helpers for the first-visit intake ask and re-ask.

The intro of every ask is one of the fixed wordings below, rotated so two consecutive asks
never open the same way. The model used to write it, and a small model turned it into
three paragraphs (greeting, "a professional must evaluate you", a request for a phone
number and an administration hand-off) above the field list.
"""

import re
import unicodedata

#: Fixed wordings. Openings (first two words) are distinct within each tuple so a rotation
#: never lands on the same one.
FIRST_ASK_INTROS = (
    "Para dejarte registrado necesito que me pases estos datos:",
    "Perfecto, para registrarte necesito estos datos:",
    "Dale, pasame estos datos así te dejo registrado:",
    "Genial, para armar tu ficha me hacen falta estos datos:",
)
RETRY_ASK_INTROS = (
    "Gracias. Todavía me faltan estos datos:",
    "Ya casi estamos, solo me quedan estos datos:",
    "Para terminar necesito que me pases:",
    "Listo, me quedaron pendientes estos datos:",
)

#: Separates the intro from the bullet list the node appends after it.
_BULLETS_SEPARATOR = "\n\n- "
_OPENING_WORDS = 2


def _words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^\w\s]", " ", plain).split()


def previous_intake_intro(recent_messages: list[dict[str, str]]) -> str | None:
    """The intro of the last assistant message when that message was an intake ask."""
    for message in reversed(recent_messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if _BULLETS_SEPARATOR not in content:
            return None
        return content.split(_BULLETS_SEPARATOR)[0].strip()
    return None


def repeats_opening(intro: str, previous: str | None) -> bool:
    """True when both intros start with the same words (case, accents, punctuation aside)."""
    if previous is None:
        return False
    opening = _words(intro)[:_OPENING_WORDS]
    return bool(opening) and opening == _words(previous)[:_OPENING_WORDS]


def pick_static_intro(options: tuple[str, ...], previous: str | None, salt: int) -> str:
    """A static intro that does not open like `previous`, rotating with `salt`."""
    candidates = [option for option in options if not repeats_opening(option, previous)]
    return candidates[salt % len(candidates)]
