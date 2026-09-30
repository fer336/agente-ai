import pytest

from app.agent.action_claims import (
    SAFE_DIAGNOSIS_ANSWER,
    guard_free_text_answer,
    offers_diagnosis,
)

_AUDIT_REPLY = (
    "Por lo que describís, podría tratarse de una caries o una sensibilidad profunda. "
    "Lo ideal es que te vea un odontólogo."
)


@pytest.mark.parametrize(
    "text",
    [
        _AUDIT_REPLY,
        "Parece una infección, conviene que lo revisen.",
        "Probablemente sea un absceso.",
        "Probablemente tengas gingivitis.",
        "Es una caries seguro.",
        "Puede ser una fractura del diente.",
        "Podría ser bruxismo.",
        "Eso suena a una pulpitis.",
        "Tomá ibuprofeno cada 8 horas hasta que te vean.",
        "Podés tomar un antibiótico para el dolor.",
    ],
)
def test_diagnosis_like_phrasing_is_detected(text):
    assert offers_diagnosis(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Lo tiene que ver un profesional. ¿Querés sacar un turno?",
        "Eso lo tiene que evaluar un odontólogo.",
        "Tenemos turnos para caries y limpieza.",
        "Atendemos por dolor de muelas, sacá un turno y te revisan.",
        "Podría ser un buen momento para sacar turno.",
        "Parece que hay lugar el lunes.",
        "",
    ],
)
def test_ordinary_clinic_answers_are_not_diagnoses(text):
    assert offers_diagnosis(text) is False


def test_a_diagnosis_answer_is_replaced_by_the_safe_static_reply():
    assert guard_free_text_answer(_AUDIT_REPLY) == SAFE_DIAGNOSIS_ANSWER
    assert SAFE_DIAGNOSIS_ANSWER == (
        "No puedo darte un diagnóstico por acá: lo tiene que evaluar un profesional. "
        "¿Querés sacar un turno para que te revisen?"
    )
    assert offers_diagnosis(SAFE_DIAGNOSIS_ANSWER) is False
