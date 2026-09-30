import pytest

from app.agent.action_claims import claims_executed_action


@pytest.mark.parametrize(
    "text",
    [
        "Buenísimo, ahí te lo confirmo entonces. Nos vemos el lunes! 👍",
        "Dale, ahí te lo cancelo entonces.",
        "Dale, ahí te lo cancelo. Para que quede registrado en el sistema, pasame tu nombre",
        "Ya te anoté para el martes.",
        "Ya lo cancelé, quedate tranquilo.",
        "Listo, turno confirmado.",
        "Listo! Quedó cancelado.",
        "Tu turno quedó confirmado para el lunes.",
        "Tu turno ya está cancelado.",
        "Te lo reprogramo para el jueves.",
        "Te reservo el turno de las 10.",
        "Confirmé tu turno.",
        "Nos vemos el lunes!",
        "Te esperamos el martes a las 10.",
        "Cancelamos tu turno.",
    ],
)
def test_claims_of_an_executed_action_are_detected(text):
    assert claims_executed_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "¿Querés que te lo confirme?",
        "Tocá Confirmar para reservarlo.",
        "Para confirmarlo tocá ✅ Confirmar abajo, o ❌ Cancelar si no querés seguir.",
        "Todavía no está confirmado: tocá ✅ Confirmar.",
        "Cuando toques Confirmar, el turno queda confirmado.",
        "Si querés cancelarlo, tocá ❌ Cancelar.",
        "Te confirmo que atendemos los sábados de 9 a 13.",
        "Te confirmo si aceptamos OSDE con administración.",
        "Listo, descartamos esa propuesta. Necesitás algo más?",
        "El lunes tenemos horarios disponibles.",
        "Por favor, confirmá o cancelá tocando uno de los botones.",
        "",
    ],
)
def test_pending_or_informational_wording_is_not_a_claim(text):
    assert claims_executed_action(text) is False
