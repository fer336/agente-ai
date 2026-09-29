import pytest

from app.agent.handoff_offer import (
    HANDOFF_OFFER_BUTTONS,
    is_handoff_offer_acceptance,
    is_main_menu_request,
    offers_administration_handoff,
)
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD


def test_the_handoff_offer_buttons_are_administracion_and_the_main_menu():
    assert [(button.id, button.title) for button in HANDOFF_OFFER_BUTTONS] == [
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Sí, atendemos pacientes particulares. Si querés, puedo pasarte con administración "
        "para que te confirmen los valores. ¿Te parece bien?",
        "Ese dato no lo tengo confirmado. Si querés, te comunico con administración.",
        "Puedo derivarte con Administración si preferís.",
        "No encontramos turnos próximos a tu nombre. Querés que te comunique con administración?",
    ],
)
def test_an_offer_to_hand_over_to_administration_is_detected(text):
    assert offers_administration_handoff(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Atendemos de lunes a viernes de 9 a 18.",
        "Administración atiende de lunes a viernes.",
        "Sí, atendemos particulares.",
    ],
)
def test_plain_answers_are_not_handoff_offers(text):
    assert offers_administration_handoff(text) is False


@pytest.mark.parametrize(
    "text", ["Bueno", "bueno!", "Dale", "sí", "Si", "ok", "Ok, dale", "Sí, por favor", "Listo"]
)
def test_short_agreements_accept_the_offer(text):
    assert is_handoff_offer_acceptance(text) is True


@pytest.mark.parametrize(
    "text", ["no", "No gracias", "quiero un turno", "bueno pero quiero cancelar un turno", ""]
)
def test_anything_else_does_not_accept_the_offer(text):
    assert is_handoff_offer_acceptance(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Menú principal",
        "menu principal",
        "  Menú Principal! ",
        "volver al menú",
        "ir al menú principal",
    ],
)
def test_typed_main_menu_requests_are_recognised(text):
    assert is_main_menu_request(text) is True


@pytest.mark.parametrize("text", ["quiero un turno", "el menú de precios", "principal"])
def test_other_text_is_not_a_main_menu_request(text):
    assert is_main_menu_request(text) is False
