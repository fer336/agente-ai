import pytest

from app.agent.thanks import is_pure_thanks, llm_thanks_is_safe

_THANKS_ANYWHERE = [
    "Gracias",
    "gracias!",
    "GRACIAS!!!",
    "Muchas gracias",
    "muchísimas gracias",
    "Mil gracias",
    "gracias por todo",
    "Muchas gracias por todo",
    "gracias por la info",
    "gracias por la ayuda",
    "Gracias por la atención",
    "te agradezco",
    "Te agradezco mucho",
    "🙏",
    "gracias 🙏",
    "Gracias 😊",
    "graciassss",
    "graciaaas!",
    "ok gracias",
    "Ok, gracias",
    "dale gracias",
    "dale, gracias!",
    "perfecto gracias",
    "Genial, gracias",
    "buenísimo gracias",
    "listo gracias",
    "Listo, gracias.",
    "gracias, hasta luego",
    "Gracias, chau",
    "chau gracias",
    "  gracias  ",
]

_ACKNOWLEDGEMENTS_WITHOUT_THANKS = [
    "ok",
    "Ok!",
    "oka",
    "okey",
    "okk",
    "dale",
    "Dale!",
    "listo",
    "perfecto",
    "Perfecto!",
    "genial",
    "buenísimo",
    "excelente",
    "👍",
    "ok perfecto",
    "dale listo",
    "chau",
]

_NOT_THANKS = [
    "gracias, quiero un turno",
    "gracias, y la dirección?",
    "gracias pero necesito cancelar",
    "gracias, ¿atienden los sábados?",
    "gracias?",
    "no gracias",
    "No, gracias",
    "no gracias, mejor no",
    "gracias pero no",
    "gracias, quiero cancelar mi turno",
    "gracias doctor Pérez",
    "gracias por nada, qué mal servicio",
    "quiero un turno",
    "hola",
    "buen día",
    "sí",
    "no",
    "",
    "   ",
    "por todo",
    "la info",
    "ok quiero un turno",
    "dale, agendame",
    "perfecto, y cuánto sale?",
]


@pytest.mark.parametrize("text", _THANKS_ANYWHERE)
@pytest.mark.parametrize("stage_awaits_answer", [False, True])
def test_thanks_with_the_word_gracias_counts_at_any_point(text, stage_awaits_answer):
    assert is_pure_thanks(text, stage_awaits_answer=stage_awaits_answer) is True


@pytest.mark.parametrize("text", _ACKNOWLEDGEMENTS_WITHOUT_THANKS)
def test_bare_acknowledgements_count_only_when_no_stage_awaits_an_answer(text):
    assert is_pure_thanks(text, stage_awaits_answer=False) is True
    assert is_pure_thanks(text, stage_awaits_answer=True) is False


@pytest.mark.parametrize("text", _NOT_THANKS)
@pytest.mark.parametrize("stage_awaits_answer", [False, True])
def test_anything_that_asks_declines_or_carries_other_content_is_not_thanks(
    text, stage_awaits_answer
):
    assert is_pure_thanks(text, stage_awaits_answer=stage_awaits_answer) is False


@pytest.mark.parametrize(
    ("text", "stage_awaits_answer", "expected"),
    [
        ("muchas gracias por todo, en serio", False, True),
        ("no gracias", False, False),
        ("No, gracias", True, False),
        ("sí gracias", True, False),
        ("si, gracias", False, False),
        ("dale", True, False),
        ("dale", False, True),
        ("gracias, quiero un turno", False, False),
        ("¿gracias?", False, False),
    ],
)
def test_llm_thanks_verdict_is_vetoed_by_declines_agreements_and_requests(
    text, stage_awaits_answer, expected
):
    assert llm_thanks_is_safe(text, stage_awaits_answer=stage_awaits_answer) is expected
