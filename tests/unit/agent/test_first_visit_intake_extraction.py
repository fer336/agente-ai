import pytest

from app.agent.first_visit_intake_extraction import (
    detect_first_visit_answer,
    extract_intake_reply,
    extract_question_reply,
)
from app.domain.repositories.llm_provider import ExtractionResult
from app.infrastructure.llm.exceptions import LLMTimeoutError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider


class _ScriptedExtractionLLM(FakeLLMProvider):
    """Returns a canned extraction and records the fields it was asked for."""

    def __init__(self, fields: dict[str, object]) -> None:
        super().__init__()
        self._fields = fields
        self.asked: list[list[str]] = []

    async def extract_information(self, message, required_fields):
        self.asked.append(list(required_fields))
        found = {k: v for k, v in self._fields.items() if k in required_fields}
        return ExtractionResult(
            fields=found, missing_fields=[f for f in required_fields if f not in found]
        )


class _FailingExtractionLLM(FakeLLMProvider):
    async def extract_information(self, message, required_fields):
        raise LLMTimeoutError("boom")


@pytest.mark.asyncio
async def test_email_and_dni_are_extracted_deterministically_without_the_llm():
    llm = _ScriptedExtractionLLM({})

    reply = await extract_intake_reply(
        llm, "mi dni es 30.123.456 y mi mail ana@example.com", ["dni", "email"]
    )

    assert reply.details == {"dni": "30123456", "email": "ana@example.com"}
    assert llm.asked == []


@pytest.mark.asyncio
async def test_free_text_fields_come_from_the_llm_extraction():
    llm = _ScriptedExtractionLLM({"obra_social": "OSDE", "plan": "210"})

    reply = await extract_intake_reply(
        llm, "ana@example.com, tengo OSDE 210", ["email", "obra_social", "plan"]
    )

    assert reply.details == {"email": "ana@example.com", "obra_social": "OSDE", "plan": "210"}
    assert llm.asked == [["obra_social", "plan"]]


@pytest.mark.asyncio
async def test_only_missing_fields_are_requested_from_the_llm():
    llm = _ScriptedExtractionLLM({"nombre_completo": "Ana Pérez"})

    reply = await extract_intake_reply(llm, "Ana Pérez", ["full_name", "plan"])

    assert reply.details == {"full_name": "Ana Pérez"}
    assert llm.asked == [["nombre_completo", "plan"]]


@pytest.mark.asyncio
async def test_a_lone_free_text_answer_fills_the_single_missing_field_when_the_llm_fails():
    reply = await extract_intake_reply(_FailingExtractionLLM(), "OSDE", ["obra_social"])

    assert reply.details == {"obra_social": "OSDE"}


@pytest.mark.asyncio
async def test_llm_failure_never_guesses_when_several_free_text_fields_are_missing():
    reply = await extract_intake_reply(_FailingExtractionLLM(), "OSDE 210", ["obra_social", "plan"])

    assert reply.details == {}


@pytest.mark.asyncio
async def test_llm_failure_never_guesses_a_full_name():
    reply = await extract_intake_reply(_FailingExtractionLLM(), "hola quiero turno", ["full_name"])

    assert reply.details == {}


@pytest.mark.parametrize(
    "text",
    [
        "no, ya soy paciente",
        "No es mi primera vez",
        "ya soy paciente de la clínica",
        "ya me atiendo ahí",
        "no",
        "sí, ya fui",
        "soy paciente",
        "Soy paciente de la clínica",
    ],
)
@pytest.mark.asyncio
async def test_existing_patient_answers_are_recognised(text):
    reply = await extract_intake_reply(_ScriptedExtractionLLM({}), text, ["email"])

    assert reply.first_visit == "existing"


@pytest.mark.parametrize("text", ["sí, es mi primera vez", "si", "Primera vez"])
@pytest.mark.asyncio
async def test_new_patient_answers_are_recognised(text):
    reply = await extract_intake_reply(_ScriptedExtractionLLM({}), text, ["email"])

    assert reply.first_visit == "new"


@pytest.mark.asyncio
async def test_first_visit_phrase_is_not_taken_as_a_free_text_field_value():
    reply = await extract_intake_reply(_FailingExtractionLLM(), "sí, primera vez", ["obra_social"])

    assert reply.first_visit == "new"
    assert reply.details == {}


@pytest.mark.parametrize(
    "text",
    [
        "no soy paciente",
        "no, no soy paciente todavía",
        "todavía no soy paciente",
        "nunca fui",
        "no, nunca fui a la clínica",
    ],
)
@pytest.mark.asyncio
async def test_negated_existing_patient_phrases_are_read_as_a_first_visit(text):
    reply = await extract_intake_reply(_ScriptedExtractionLLM({}), text, ["email"])

    assert reply.first_visit == "new"


@pytest.mark.parametrize(
    "text",
    ["soy paciente de OSDE", "tengo OSDE, soy paciente de OSDE 210"],
)
@pytest.mark.asyncio
async def test_incidental_soy_paciente_de_an_insurer_is_not_an_existing_patient(text):
    reply = await extract_intake_reply(_ScriptedExtractionLLM({}), text, ["email"])

    assert reply.first_visit is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sí, es la primera", "new"),
        ("no soy paciente", "new"),
        ("Confirmar", "new"),
        ("no, ya soy paciente", "existing"),
        ("no", "existing"),
        ("Cancelar", "existing"),
        ("quizás más tarde", None),
        ("", None),
    ],
)
def test_detect_first_visit_answer_reads_the_question_reply(text, expected):
    assert detect_first_visit_answer(text) == expected


@pytest.mark.parametrize("text", ["Cancelar", "Confirmar", "cancelo", "confirmo"])
@pytest.mark.asyncio
async def test_button_words_do_not_answer_the_first_visit_question_during_collection(text):
    reply = await extract_intake_reply(_FailingExtractionLLM(), text, ["email"])

    assert reply.first_visit is None


@pytest.mark.asyncio
async def test_a_bare_button_word_reply_to_the_question_skips_field_extraction():
    llm = _ScriptedExtractionLLM({"nombre_completo": "Cancelar"})

    reply = await extract_question_reply(llm, "Cancelar", ["full_name", "dni"])

    assert reply.first_visit == "existing"
    assert reply.details == {}
    assert llm.asked == []


@pytest.mark.asyncio
async def test_a_first_visit_reply_to_the_question_keeps_its_inline_details():
    llm = _ScriptedExtractionLLM({"nombre_completo": "Juan Perez"})

    reply = await extract_question_reply(
        llm, "sí, es la primera, soy Juan Perez DNI 30123456", ["full_name", "dni", "email"]
    )

    assert reply.first_visit == "new"
    assert reply.details == {"full_name": "Juan Perez", "dni": "30123456"}


@pytest.mark.asyncio
async def test_an_existing_patient_reply_to_the_question_keeps_name_and_dni():
    llm = _ScriptedExtractionLLM({"nombre_completo": "Juan Perez"})

    reply = await extract_question_reply(
        llm, "ya soy paciente, Juan Perez 30123456", ["full_name", "dni"]
    )

    assert reply.first_visit == "existing"
    assert reply.details == {"full_name": "Juan Perez", "dni": "30123456"}


@pytest.mark.asyncio
async def test_an_unclear_reply_to_the_question_discards_extracted_details():
    llm = _ScriptedExtractionLLM({"obra_social": "quizás"})

    reply = await extract_question_reply(llm, "quizás", ["obra_social"])

    assert reply.first_visit is None
    assert reply.details == {}
