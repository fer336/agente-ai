"""Deterministic detector for payment questions.

Payments, advances, installments and any other price are handled directly by
Administración (PRD.md, frequent topics): the agent never improvises about them. Only
payment-specific terms count; a bare "cuánto sale/cuesta" is a price question that a
clinic topic may answer.
"""

import re

from app.agent.handoff_offer import normalize_text

#: Accent-folded terms (see `normalize_text`), matched as whole words or phrases.
_PAYMENT_TERMS = (
    "anticipo",
    "anticipos",
    "sena",
    "senia",
    "cuota",
    "cuotas",
    "financiacion",
    "financiamiento",
    "financiar",
    "financiado",
    "forma de pago",
    "formas de pago",
    "medio de pago",
    "medios de pago",
    "metodo de pago",
    "metodos de pago",
    "como se paga",
    "como pago",
    "como abono",
    "pagar",
    "abonar",
    "puedo pagar",
    "se puede pagar",
    "aceptan tarjeta",
    "tarjeta",
    "tarjetas",
    "efectivo",
    "transferencia",
    "transferencias",
    "mercado pago",
    "debito",
    "credito",
    "pagos",
    "cuando se paga",
)

_PAYMENT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in _PAYMENT_TERMS) + r")\b"
)

#: The insurance card ("la tarjeta de mi obra social") is not a payment card.
_INSURANCE_CARD_PATTERN = re.compile(
    r"\btarjetas? de (?:mi |la |su |nuestra )?"
    r"(?:obra social|prepaga|cobertura|osde|medife|swiss medical|galeno|william hope)\b"
)


def asks_about_payments(text: str) -> bool:
    """True when the message names payments, advances, installments or payment methods."""
    normalized = _INSURANCE_CARD_PATTERN.sub(" ", normalize_text(text))
    return _PAYMENT_PATTERN.search(normalized) is not None
