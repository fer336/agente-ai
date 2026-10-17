import pytest

from app.agent.faq_scope import asks_about_programmed_faq


@pytest.mark.parametrize(
    "message",
    [
        "¿Cuánto cuesta el blanqueamiento?",
        "precio de la consulta",
        "¿Cuánto sale una limpieza?",
        "quiero info",
        "Consultas frecuentes",
        "¿Qué valores manejan?",
        "¿Tienen alineadores?",
        # Not programmed, but a price question: the menu showing the topics is acceptable.
        "¿Cuánto cuesta un implante?",
        "¿Cuánto sale una corona?",
    ],
)
def test_a_programmed_topic_or_a_price_question_may_show_the_faq_menu(message: str) -> None:
    assert asks_about_programmed_faq(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "¿Cómo se hace un flan casero?",
        "¿Cómo hago un bucle for en JavaScript?",
        "¿A qué hora abre el banco?",
        "diagnóstico por foto",
        "¿Cuánto es 2 más 2?",
    ],
)
def test_an_off_topic_question_does_not_show_the_faq_menu(message: str) -> None:
    assert asks_about_programmed_faq(message) is False
