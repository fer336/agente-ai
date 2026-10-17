import pytest

from app.agent.greetings import is_greeting


@pytest.mark.parametrize(
    "message",
    [
        "Hola",
        "Buen día",
        "Buenas tardes",
        "Hola, quiero info",
        "Holaa",
        "HOLA",
        "Buenas",
        "Hola, ¿cómo andan?",
        "holaaa buenas tardes",
    ],
)
def test_a_greeting_is_recognised(message: str) -> None:
    assert is_greeting(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "",
        "Quiero un turno",
        "Hola, quiero un turno",
        "Hola, me duele una muela",
        "Hola, ¿dónde queda la clínica?",
        "¿Cómo se hace un flan casero?",
        "gracias",
        "dame una receta",
        "Hola quiero cancelar mi turno de mañana por favor",
    ],
)
def test_a_message_with_a_request_is_not_a_greeting(message: str) -> None:
    assert is_greeting(message) is False
