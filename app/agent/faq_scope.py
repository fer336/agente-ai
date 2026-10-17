"""Whether a free-text message plausibly asks about one of the programmed FAQ topics.

The LLM label `faq_topic` is broad ("asks about prices or how something works") and the real
model also applied it to off-topic questions (a recipe, code, the bank's opening hours). The
FAQ menu may only appear when the message mentions a programmed topic, a price/cost word or
asks for the frequent questions in general; anything else gets the fixed out-of-scope reply.
A price question about a treatment that is not programmed (implante, corona) still lands on
the menu, which is acceptable: it shows the programmed topics.
"""

import re

from app.agent.clinic_topics import match_clinic_topic
from app.agent.handoff_offer import normalize_text

_PRICE_OR_GENERIC = re.compile(
    r"\b(?:precios?|valor(?:es)?|costos?|cuesta\w*|cuanto\s+(?:sale\w*|cobran|vale\w*)|"
    r"tarifas?|promos?|promociones?|presupuestos?|aranceles?|"
    r"consultas?\s+frecuentes?|preguntas?\s+frecuentes?|temas?\s+frecuentes?|faq|"
    r"info|informacion)\b"
)


def asks_about_programmed_faq(text: str) -> bool:
    """True when the message names a programmed topic, asks a price or asks for general info."""
    if match_clinic_topic(text) is not None:
        return True
    return _PRICE_OR_GENERIC.search(normalize_text(text)) is not None
