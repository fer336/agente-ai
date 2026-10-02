"""`booking_comment`: the text administration reads in the Dentalink appointment comment."""

import pytest

from app.agent.clinic_topics import CLINIC_TOPICS, booking_comment


@pytest.mark.parametrize(
    ("topic_id", "expected"),
    [
        ("blanqueamiento", "Consulta frecuente: Blanqueamiento"),
        ("consulta_particular", "Consulta frecuente: Consulta Particular"),
        ("limpieza_particular", "Consulta frecuente: Limpieza Particular"),
        ("brackets_obra_social", "Consulta frecuente: Brackets por obra social"),
        ("alineadores", "Consulta frecuente: Alineadores"),
    ],
)
def test_each_topic_has_its_exact_comment(topic_id, expected):
    assert booking_comment(topic_id) == expected


@pytest.mark.parametrize("option", ["1", "2", "3"])
def test_alineadores_with_an_option_names_the_option(option):
    assert booking_comment("alineadores", option) == (
        f"Consulta frecuente: Alineadores - Opción {option}"
    )


def test_an_option_is_ignored_for_a_topic_without_options():
    assert booking_comment("blanqueamiento", "2") == "Consulta frecuente: Blanqueamiento"


@pytest.mark.parametrize("topic_id", ["", "nope", "FAQ_BOOK:blanqueamiento", None])
def test_an_unknown_topic_has_no_comment(topic_id):
    assert booking_comment(topic_id) is None  # type: ignore[arg-type]


def test_every_topic_carries_a_comment_label():
    assert all(topic.comment_label for topic in CLINIC_TOPICS)
