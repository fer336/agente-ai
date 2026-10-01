import pytest

from app.agent.payment_questions import asks_about_payments


@pytest.mark.parametrize(
    "text",
    [
        "aceptan tarjeta?",
        "Aceptan tarjeta de crédito",
        "cuánto es el anticipo",
        "hay que dejar seña?",
        "se puede pagar en cuotas",
        "tienen financiación?",
        "puedo financiar el tratamiento",
        "cuáles son las formas de pago",
        "qué medios de pago aceptan",
        "como se paga",
        "cómo pago?",
        "puedo pagar en efectivo",
        "aceptan transferencia",
        "trabajan con mercado pago",
        "pagan con débito?",
        "cuándo se paga",
        "cuotas para el blanqueamiento",
        "quiero pagar la consulta",
        "dónde puedo abonar",
        "tengo que pagar antes?",
    ],
)
def test_payment_questions_are_detected(text):
    assert asks_about_payments(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "cuánto sale el blanqueamiento",
        "cuánto cuesta una limpieza",
        "tengo osde",
        "quiero un turno",
        "me pagan el sueldo",
        "tengo la tarjeta de mi obra social",
        "perdí la tarjeta de la prepaga",
        "mi tarjeta de osde está vencida",
        "hola",
        "el senado",
        "",
    ],
)
def test_other_messages_are_not_payment_questions(text):
    assert asks_about_payments(text) is False
