import pytest

from app.domain.value_objects.interactive_button import InteractiveButton


def test_accepts_a_short_title():
    button = InteractiveButton(id="PAYLOAD", title="Confirmar")

    assert button.title == "Confirmar"


def test_accepts_a_title_at_exactly_the_20_character_limit():
    title = "12345678901234567890"
    assert len(title) == 20

    button = InteractiveButton(id="PAYLOAD", title=title)

    assert button.title == title


def test_rejects_a_title_longer_than_20_characters():
    # Regression, seen live: "🔎 Ver otros profesionales" (25 characters)
    # shipped as a static, hardcoded button title and silently failed to
    # send in production — WhatsApp's own API rejected it (YCloud error
    # 131009: "Button title length invalid. Min length: 1, Max length:
    # 20"), with no local/CI signal at all before this.
    with pytest.raises(ValueError, match="1-20 characters"):
        InteractiveButton(id="PAYLOAD", title="🔎 Ver otros profesionales")


def test_rejects_an_empty_title():
    with pytest.raises(ValueError, match="1-20 characters"):
        InteractiveButton(id="PAYLOAD", title="")
