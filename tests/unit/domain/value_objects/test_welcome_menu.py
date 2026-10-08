from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

_MENU_PROMPT = "Elegí una opción del menú tocando el botón de abajo 👇"


def test_welcome_text_greets_with_the_opening_exclamation_mark():
    assert WELCOME_TEXT.startswith("¡Hola! 👋 Bienvenido/a a *Smiling Pilar* 🦷")


def test_welcome_text_ends_with_the_menu_prompt_on_its_own_line():
    paragraphs = WELCOME_TEXT.split("\n\n")

    # The instruction is its own last paragraph, below the question, never on the same line.
    assert paragraphs[-1] == _MENU_PROMPT
    assert paragraphs[-2] == "¿En qué te puedo ayudar hoy?"
    assert "¿En qué te puedo ayudar hoy? Elegí" not in WELCOME_TEXT


def test_welcome_text_keeps_the_clinic_information():
    assert "Centro Odontológico Integral" in WELCOME_TEXT
    assert "lunes a viernes de *9:00* a *18:00*" in WELCOME_TEXT
    assert "instagram.com/smiling.pilar" in WELCOME_TEXT


def test_welcome_text_fits_a_whatsapp_interactive_body_and_the_list_has_its_button():
    assert len(WELCOME_TEXT) <= 1024
    assert WELCOME_LIST.button_label == "Elegí una opción"
