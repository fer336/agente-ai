import pytest

from app.agent.nodes.llm_response import (
    conversation_started,
    generate_or_fallback,
    strip_leading_greeting,
)
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider

_STARTED = [
    {"role": "user", "content": "Hola"},
    {"role": "assistant", "content": "Hola! Soy el asistente de Smiling Pilar."},
    {"role": "user", "content": "¿atienden particulares?"},
]
_FIRST_TURN = [{"role": "user", "content": "Hola"}]


class _ScriptedLLM(FakeLLMProvider):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.contexts: list[ResponseContext] = []

    async def generate_response(self, context: ResponseContext) -> str:
        self.contexts.append(context)
        return self._text


def test_the_conversation_has_started_once_the_assistant_already_spoke():
    assert conversation_started(_STARTED) is True
    assert conversation_started(_FIRST_TURN) is False
    assert conversation_started([]) is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("¡Hola! Sí, atendemos pacientes particulares.", "Sí, atendemos pacientes particulares."),
        ("Hola, sí atendemos particulares.", "Sí atendemos particulares."),
        ("Hola! Si querés, te paso con administración.", "Si querés, te paso con administración."),
        (
            "Buenas tardes! Te cuento: atendemos de lunes a viernes.",
            "Te cuento: atendemos de lunes a viernes.",
        ),
        ("hola che, dale", "Dale"),
        ("¡Hola Fernando! Ya te anoté.", "Ya te anoté."),
        ("Holanda queda lejos.", "Holanda queda lejos."),
        ("Sí, hola de nuevo no hace falta.", "Sí, hola de nuevo no hace falta."),
        ("Hola", "Hola"),
    ],
)
def test_a_leading_greeting_is_stripped(raw, expected):
    assert strip_leading_greeting(raw) == expected


@pytest.mark.asyncio
async def test_generated_text_never_starts_with_a_greeting_mid_conversation():
    llm = _ScriptedLLM("¡Hola! Sí, atendemos particulares.")

    text = await generate_or_fallback(llm, "conv-1", "question", {}, "static", _STARTED, None)

    assert text == "Sí, atendemos particulares."


@pytest.mark.asyncio
async def test_the_first_reply_of_a_conversation_may_greet():
    llm = _ScriptedLLM("¡Hola! Sí, atendemos particulares.")

    text = await generate_or_fallback(llm, "conv-1", "question", {}, "static", _FIRST_TURN, None)

    assert text == "¡Hola! Sí, atendemos particulares."


@pytest.mark.asyncio
async def test_the_provider_is_told_whether_the_conversation_already_started():
    llm = _ScriptedLLM("ok")

    await generate_or_fallback(llm, "conv-1", "question", {}, "static", _STARTED, None)
    await generate_or_fallback(llm, "conv-1", "question", {}, "static", _FIRST_TURN, None)

    assert [context.conversation_started for context in llm.contexts] == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        "Buenísimo, ahí te lo confirmo entonces. Nos vemos el lunes! 👍",
        "Dale, ahí te lo cancelo entonces.",
    ],
)
async def test_a_reply_claiming_an_executed_action_is_replaced_by_the_static_text(claim):
    llm = _ScriptedLLM(claim)

    text = await generate_or_fallback(
        llm, "conv-1", "confirmation_reminder", {}, "STATIC", _STARTED, None
    )

    assert text == "STATIC"


@pytest.mark.asyncio
async def test_a_post_execution_reply_may_report_the_executed_action():
    llm = _ScriptedLLM("Listo, tu turno quedó confirmado para el lunes.")

    text = await generate_or_fallback(
        llm,
        "conv-1",
        "create_success",
        {},
        "STATIC",
        _STARTED,
        None,
        action_executed=True,
    )

    assert text == "Listo, tu turno quedó confirmado para el lunes."


@pytest.mark.asyncio
async def test_a_diagnosis_reply_is_replaced_by_the_static_text():
    llm = _ScriptedLLM("Por lo que describís, podría tratarse de una caries.")

    text = await generate_or_fallback(llm, "conv-1", "fallback", {}, "STATIC", _STARTED, None)

    assert text == "STATIC"
