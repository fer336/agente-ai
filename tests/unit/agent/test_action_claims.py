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
        # A bare affirmative "si"/"sí" is not a conditional clause.
        "Buenísimo, si, te lo confirmo.",
        "Dale si, ya te anoté.",
        "Dale sí, te lo cancelo.",
        "Apenas te lo confirmo, nos vemos.",
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
        "Si tocás Confirmar, te lo confirmo.",
        "Si querés, te lo cancelo apenas toques Cancelar.",
        "Apenas toques Confirmar te lo reservo.",
        "Para que te lo reserve, tocá ✅ Confirmar.",
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


@pytest.mark.parametrize(
    "text",
    [
        # Audit 2026-10-03: the reply typed at the cancel confirmation stage.
        "ahí lo cancelo entonces",
        "Ahí lo cancelo entonces.",
        "Ahi lo cancelo",
        "Dale, lo cancelo.",
        "te lo cancelo",
        "Lo cancelo ya.",
        "LO CANCELO YA",
        "Cancelo el turno ahora mismo.",
        "Cancelo tu turno.",
        "Procedo a cancelar el turno.",
        "Procedo a agendarlo.",
        "Procedo a reprogramar tu cita.",
        "Perfecto, lo agendo.",
        "Dale, te lo agendo para el jueves.",
        "Agendo tu turno ahora.",
        "Ahí lo reprogramo.",
        "Te lo reprogramo.",
        "Lo reagendo enseguida.",
        "Ya lo hago.",
        "Listo, lo hago.",
        "Listo! Lo hago ya.",
        "Sí, ya lo cancelo.",
    ],
)
def test_present_or_future_claims_of_doing_the_action_right_now_are_detected(text):
    assert claims_executed_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Para cancelar necesito que confirmes con los botones.",
        "Si querés cancelar, usá los botones.",
        "No puedo cancelar sin tu confirmación.",
        "¿Querés que lo cancele?",
        "¿Querés que lo agende?",
        "Si tocás Cancelar, lo cancelo.",
        "Cuando toques Confirmar lo agendo.",
        "Para que lo cancele, tocá ❌ Cancelar.",
        "No lo cancelo hasta que toques el botón.",
        "Todavía no lo cancelo: falta tu confirmación.",
        "Podés cancelar tocando el botón ❌ Cancelar.",
        "Agendamos turnos de lunes a viernes.",
        "Tocá el botón para que procedamos a cancelarlo.",
        "Para proceder a cancelar tocá ❌ Cancelar.",
        "Si querés que lo hagamos, tocá Confirmar.",
    ],
)
def test_pending_wording_about_the_action_is_still_not_a_claim(text):
    assert claims_executed_action(text) is False
