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

#: An offer addressed to the patient by the agent, on accent-free lowercase text:
#: "puedo pasarte con", "querés que te comunique", "te paso con". A bare verb stem is
#: not enough ("podés pasar por administración", "datos de contacto").
_OFFER = re.compile(
    r"\b(?:puedo|podemos|podria|podriamos)\s+(?:\w+\s+){0,2}"
    r"(?:pasarte|comunicarte|derivarte|contactarte|conectarte|transferirte)\b"
    r"|\b(?:queres|quiere|preferis)\s+que\s+te\s+"
    r"(?:pase|comunique|derive|contacte|conecte|transfiera)\b"
    r"|\bte\s+(?:comunico|paso|derivo|contacto|conecto|transfiero)\s+con\b"
)

_AGREEMENT_CORE = frozenset(
    {
        "si",
        "bueno",
        "dale",
        "ok",
        "okey",
        "oka",
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
_AGREEMENT_FILLER = frozenset({"por", "favor", "de", "acuerdo", "que", "si"})

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


def normalize_text(text: str) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w\s]", " ", without_accents).split())


def offers_administration_handoff(text: str) -> bool:
    """True when the text offers to hand the patient over to administration."""
    normalized = normalize_text(text)
    return "administracion" in normalized and _OFFER.search(normalized) is not None


def is_handoff_offer_acceptance(text: str) -> bool:
    """True for a short free-text agreement ("bueno", "dale", "sí, por favor")."""
    tokens = normalize_text(text).split()
    if not tokens:
        return False
    if not all(token in _AGREEMENT_CORE or token in _AGREEMENT_FILLER for token in tokens):
        return False
    return any(token in _AGREEMENT_CORE for token in tokens)


def is_main_menu_request(text: str) -> bool:
    """True when the patient typed the main menu request instead of tapping the button."""
    return normalize_text(text) in _MAIN_MENU_REQUESTS
