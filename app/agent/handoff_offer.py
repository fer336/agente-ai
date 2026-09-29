"""Handing the patient over to administration when an LLM answer offers it.

The LLM's free-text answers (`understand()`'s `answer`, the "no confirmed answer"
reply) sometimes end with "si querés, puedo pasarte con administración". A plain
question mark gives the patient nothing to tap, so those messages carry two buttons
(Administración / Menú principal) and the next short "bueno"/"dale"/"sí" counts as
tapping Administración.

There is no structured signal for the offer (the model returns prose only), so it is
detected deterministically from the text.
"""

import re
import unicodedata

from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD

#: `collected_data` flag set on the turn a handoff was offered and consumed (stripped)
#: on the next one, so an agreement word only ever accepts the offer just made.
HANDOFF_OFFER_KEY = "handoff_offer_pending"

HANDOFF_OFFER_BUTTONS = [
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]

_OFFER_VERB = re.compile(r"\b(?:pas\w+|comuni[cq]\w*|deriv\w+|conect\w+|hablar|contact\w+)\b")

_AGREEMENT_CORE = frozenset(
    {
        "si",
        "bueno",
        "dale",
        "ok",
        "okey",
        "oka",
        "listo",
        "claro",
        "perfecto",
        "genial",
        "joya",
        "buenisimo",
        "vale",
        "obvio",
        "aja",
        "va",
        "bien",
    }
)
_AGREEMENT_FILLER = frozenset({"por", "favor", "gracias", "de", "acuerdo", "que", "si"})

_MAIN_MENU_REQUESTS = frozenset(
    {
        "menu principal",
        "el menu principal",
        "volver al menu",
        "volver al menu principal",
        "ir al menu",
        "ir al menu principal",
    }
)


def _normalize(text: str) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", without_accents).split())


def offers_administration_handoff(text: str) -> bool:
    """True when the text offers to hand the patient over to administration."""
    normalized = _normalize(text)
    return "administracion" in normalized and _OFFER_VERB.search(normalized) is not None


def is_handoff_offer_acceptance(text: str) -> bool:
    """True for a short free-text agreement ("bueno", "dale", "sí, por favor")."""
    tokens = _normalize(text).split()
    if not tokens:
        return False
    if not all(token in _AGREEMENT_CORE or token in _AGREEMENT_FILLER for token in tokens):
        return False
    return any(token in _AGREEMENT_CORE for token in tokens)


def is_main_menu_request(text: str) -> bool:
    """True when the patient typed the main menu request instead of tapping the button."""
    return _normalize(text) in _MAIN_MENU_REQUESTS
