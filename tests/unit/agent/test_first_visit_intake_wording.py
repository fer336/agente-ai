import pytest

from app.agent.first_visit_intake_wording import (
    FIRST_ASK_INTROS,
    RETRY_ASK_INTROS,
    pick_static_intro,
    previous_intake_intro,
    repeats_opening,
)

_BULLETS = "- Correo electrónico\n- Obra social\n- Plan"


def test_the_previous_intro_is_the_text_before_the_bullets_of_the_last_assistant_message():
    recent = [
        {
            "role": "assistant",
            "content": f"Buenísimo, gracias por la info. Todavía me faltan:\n\n{_BULLETS}",
        },
        {"role": "user", "content": "ana@example.com"},
    ]

    assert previous_intake_intro(recent) == "Buenísimo, gracias por la info. Todavía me faltan:"


@pytest.mark.parametrize(
    "recent",
    [
        [],
        [{"role": "user", "content": "hola"}],
        [{"role": "assistant", "content": "Elegí un horario tocando uno de los botones:"}],
    ],
)
def test_there_is_no_previous_intro_when_the_last_assistant_message_was_not_an_ask(recent):
    assert previous_intake_intro(recent) is None


def test_the_same_opening_is_detected_regardless_of_case_and_punctuation():
    assert repeats_opening(
        "Buenísimo, gracias por la info! Todavía faltan algunos datos:",
        "buenísimo gracias por la info. Me faltan estos:",
    )
    assert not repeats_opening("Perfecto, ya casi estamos:", "Buenísimo, gracias por la info.")
    assert not repeats_opening("Gracias, todavía faltan:", None)


@pytest.mark.parametrize("intros", [FIRST_ASK_INTROS, RETRY_ASK_INTROS])
def test_there_are_several_static_phrasings_with_distinct_openings(intros):
    assert len(intros) >= 3
    openings = {" ".join(intro.split()[:3]).casefold() for intro in intros}
    assert len(openings) == len(intros)


@pytest.mark.parametrize("intros", [FIRST_ASK_INTROS, RETRY_ASK_INTROS])
def test_two_consecutive_static_intros_never_share_the_same_opening(intros):
    previous = None
    for salt in range(12):
        picked = pick_static_intro(intros, previous, salt)
        assert not repeats_opening(picked, previous)
        previous = picked
