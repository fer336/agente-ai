"""Deterministic detection of messages that are only thanks or a short acknowledgement.

A pure thanks ("Gracias", "muchas gracias por todo", "ok gracias") is answered kindly by the
router at any point of the conversation instead of reaching the confusion fallback. The check
is intentionally strict: the WHOLE message must be thanks/closing words, so anything that also
asks, requests, declines or carries other content ("gracias, quiero un turno", "no gracias")
keeps its normal routing. Paraphrases the word lists do not cover are left to the `thanks`
label of `LLMProvider.understand` (see `llm_thanks_is_safe`).
"""

import re

from app.agent.handoff_offer import normalize_text

_THANKS_WORDS = frozenset({"gracias", "agradezco"})
_THANKS_EMOJIS = ("🙏",)
_ACKNOWLEDGEMENT_EMOJIS = ("👍",)

#: Acknowledgements that can also mean "yes" inside a stage, so they only count as thanks
#: when nothing is awaiting an answer. Closing words ("chau") live here too: a bare "chau"
#: needs no confusion reply, but it is not an answer a stage could be waiting for either.
_ACKNOWLEDGEMENT_WORDS = frozenset(
    {
        "ok",
        "oka",
        "okey",
        "okay",
        "dale",
        "listo",
        "perfecto",
        "genial",
        "buenisimo",
        "excelente",
        "barbaro",
        "joya",
        "chau",
        "chao",
        "adios",
    }
)

#: Words that may surround the thanks without adding any request.
_FILLER_WORDS = frozenset(
    {
        "muchas",
        "muchisimas",
        "muchisima",
        "mucha",
        "mil",
        "por",
        "todo",
        "la",
        "el",
        "info",
        "informacion",
        "ayuda",
        "atencion",
        "te",
        "les",
        "mucho",
        "hasta",
        "luego",
        "pronto",
    }
)

#: A request or a yes/no answer riding along with a thanks the LLM labelled as thanks.
_VETO_WORDS = frozenset(
    {
        "no",
        "si",
        "pero",
        "quiero",
        "queria",
        "necesito",
        "turno",
        "turnos",
        "cita",
        "agendar",
        "reservar",
        "sacar",
        "cancelar",
        "cambiar",
        "reagendar",
        "reprogramar",
        "mejor",
    }
)

_REPEATED_LETTERS = re.compile(r"(.)\1+")


def _collapse(word: str) -> str:
    """Folds elongations ("graciassss", "daaale") onto the plain spelling."""
    return _REPEATED_LETTERS.sub(r"\1", word)


def _vocabulary(words: frozenset[str]) -> frozenset[str]:
    return frozenset(_collapse(word) for word in words)


_THANKS = _vocabulary(_THANKS_WORDS)
_ACKNOWLEDGEMENTS = _vocabulary(_ACKNOWLEDGEMENT_WORDS)
_FILLERS = _vocabulary(_FILLER_WORDS)
_VETOES = _vocabulary(_VETO_WORDS)


def _is_question(text: str) -> bool:
    return "?" in text or "¿" in text


def _words(text: str) -> list[str]:
    return [_collapse(word) for word in normalize_text(text).split()]


def is_pure_thanks(text: str, *, stage_awaits_answer: bool) -> bool:
    """True when the whole message is thanks or a closing acknowledgement.

    `stage_awaits_answer` is True while a stage is waiting for the patient's answer: there a
    bare "ok"/"dale"/"listo" can mean "yes", so only a message that actually says thanks
    ("gracias", "te agradezco", 🙏) counts.
    """
    if _is_question(text):
        return False
    words = _words(text)
    has_thanks = any(emoji in text for emoji in _THANKS_EMOJIS) or any(
        word in _THANKS for word in words
    )
    has_acknowledgement = any(emoji in text for emoji in _ACKNOWLEDGEMENT_EMOJIS) or any(
        word in _ACKNOWLEDGEMENTS for word in words
    )
    if not words and not (has_thanks or has_acknowledgement):
        return False
    if not all(word in _THANKS or word in _ACKNOWLEDGEMENTS or word in _FILLERS for word in words):
        return False
    if has_thanks:
        return True
    return has_acknowledgement and not stage_awaits_answer


def llm_thanks_is_safe(text: str, *, stage_awaits_answer: bool) -> bool:
    """Whether to trust an LLM `thanks` verdict for `text`.

    The model reads paraphrases the word lists miss ("te lo agradezco un montón"), but it can
    also read a decline ("no, gracias") or an agreement ("sí, gracias") as thanks. Those, and
    any request riding along, veto the verdict; inside a stage the message must also say
    thanks explicitly, like the deterministic check.
    """
    if _is_question(text):
        return False
    words = _words(text)
    if any(word in _VETOES for word in words):
        return False
    if stage_awaits_answer:
        return any(emoji in text for emoji in _THANKS_EMOJIS) or any(
            word in _THANKS or word.startswith("agradec") for word in words
        )
    return True
