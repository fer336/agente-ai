import pytest

from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import LLMInvalidResponseError
from app.infrastructure.llm.openai_compatible_llm_provider import (
    DEFAULT_CLASSIFY_INTENT_PROMPT,
    DEFAULT_EXTRACT_INFORMATION_PROMPT,
    DEFAULT_GENERATE_RESPONSE_PROMPT,
    OpenAICompatibleLLMProvider,
)
from tests.fixtures.gateways import make_runtime_config_service


class _StubClient:
    """Stands in for `OpenAICompatibleLLMClient` — returns a fixed
    `chat_completion` response and records the messages it was called with.
    """

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, list[dict[str, str]], float]] = []

    async def chat_completion(
        self, model: str, messages: list[dict[str, str]], *, temperature: float = 0.0
    ) -> str:
        self.calls.append((model, messages, temperature))
        return self.content


def _make_provider(
    client: _StubClient,
    model: str = "gemini/gemini-3.7-flash",
    temperature: float = 0.0,
    classify_intent_prompt: str = DEFAULT_CLASSIFY_INTENT_PROMPT,
    extract_information_prompt: str = DEFAULT_EXTRACT_INFORMATION_PROMPT,
    generate_response_prompt: str = DEFAULT_GENERATE_RESPONSE_PROMPT,
) -> OpenAICompatibleLLMProvider:
    runtime_config_service = make_runtime_config_service(
        model=model,
        temperature=temperature,
        classify_intent_prompt=classify_intent_prompt,
        extract_information_prompt=extract_information_prompt,
        generate_response_prompt=generate_response_prompt,
    )
    return OpenAICompatibleLLMProvider(client, runtime_config_service)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_classify_intent_parses_the_models_json_response() -> None:
    client = _StubClient('{"intent": "appointment", "confidence": 0.87}')
    provider = _make_provider(client, model="gemini/gemini-3.7-flash")

    result = await provider.classify_intent("quiero un turno", context={})

    assert result.intent == "appointment"
    assert result.confidence == 0.87
    model, messages, _ = client.calls[0]
    assert model == "gemini/gemini-3.7-flash"
    assert messages[-1] == {"role": "user", "content": "quiero un turno"}


@pytest.mark.asyncio
async def test_understand_extracts_intent_and_the_mentions_in_one_call() -> None:
    client = _StubClient(
        '{"intent": "appointment", "confidence": 0.9, "answer": null,'
        ' "specialty_mention": "ortodoncia", "professional_mention": null,'
        ' "operation_mention": "create"}'
    )
    provider = _make_provider(client)

    result = await provider.understand("quiero un turno de ortodoncia", context={})

    assert result.intent == "appointment"
    assert result.specialty_mention == "ortodoncia"
    assert result.operation_mention == "create"
    assert result.answer is None
    # One call, not one to classify plus another to extract.
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_understand_returns_a_written_answer_for_a_plain_question() -> None:
    client = _StubClient(
        '{"intent": "question", "confidence": 0.95,'
        ' "answer": "Sí, atendemos los sábados por la mañana.",'
        ' "specialty_mention": null, "professional_mention": null,'
        ' "operation_mention": null}'
    )
    provider = _make_provider(client)

    result = await provider.understand("¿atienden los sábados?", context={})

    assert result.intent == "question"
    assert result.answer == "Sí, atendemos los sábados por la mañana."


@pytest.mark.asyncio
async def test_understand_tolerates_a_response_with_only_the_required_fields() -> None:
    # A smaller model often omits the null-valued keys entirely.
    client = _StubClient('{"intent": "handoff", "confidence": 0.8}')
    provider = _make_provider(client)

    result = await provider.understand("quiero hablar con alguien", context={})

    assert result.intent == "handoff"
    assert result.specialty_mention is None
    assert result.operation_mention is None


@pytest.mark.asyncio
async def test_understand_rejects_an_unknown_intent_label() -> None:
    client = _StubClient('{"intent": "comprar_pizza", "confidence": 0.9}')
    provider = _make_provider(client)

    with pytest.raises(LLMInvalidResponseError):
        await provider.understand("hola", context={})


@pytest.mark.asyncio
async def test_classify_intent_sends_the_configured_model_and_temperature() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.1}')
    provider = _make_provider(client, model="deepseek/deepseek-v4-flash", temperature=0.4)

    await provider.classify_intent("hola", context={})

    model, _, temperature = client.calls[0]
    assert model == "deepseek/deepseek-v4-flash"
    assert temperature == 0.4


@pytest.mark.asyncio
async def test_classify_intent_uses_the_configured_prompt_text() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.1}')
    provider = _make_provider(client, classify_intent_prompt="prompt editado por el admin")

    await provider.classify_intent("hola", context={})

    _, messages, _ = client.calls[0]
    assert messages[0] == {"role": "system", "content": "prompt editado por el admin"}


@pytest.mark.asyncio
async def test_classify_intent_includes_recent_messages_and_contact_memory_when_present() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.1}')
    provider = _make_provider(client)

    await provider.classify_intent(
        "hola",
        context={
            "recent_messages": [{"role": "user", "text": "hola"}],
            "contact_memory": "paciente frecuente",
        },
    )

    _, messages, _ = client.calls[0]
    joined = " ".join(m["content"] for m in messages)
    assert "paciente frecuente" in joined
    assert "hola" in joined


@pytest.mark.asyncio
async def test_classify_intent_raises_on_malformed_json() -> None:
    client = _StubClient("not json at all")
    provider = _make_provider(client)

    with pytest.raises(LLMInvalidResponseError):
        await provider.classify_intent("hola", context={})


@pytest.mark.asyncio
async def test_classify_intent_raises_on_unrecognized_intent_label() -> None:
    client = _StubClient('{"intent": "made_up_label", "confidence": 0.9}')
    provider = _make_provider(client)

    with pytest.raises(LLMInvalidResponseError):
        await provider.classify_intent("hola", context={})


@pytest.mark.asyncio
async def test_extract_information_parses_fields_and_missing_fields() -> None:
    client = _StubClient('{"fields": {"full_name": "Juan Perez"}, "missing_fields": ["dni"]}')
    provider = _make_provider(client)

    result = await provider.extract_information(
        "me llamo Juan Perez", required_fields=["full_name", "dni"]
    )

    assert result.fields == {"full_name": "Juan Perez"}
    assert result.missing_fields == ["dni"]


@pytest.mark.asyncio
async def test_extract_information_substitutes_required_fields_into_the_configured_prompt() -> None:
    client = _StubClient('{"fields": {}, "missing_fields": []}')
    provider = _make_provider(client, extract_information_prompt="Necesito: {required_fields}.")

    await provider.extract_information("hola", required_fields=["full_name", "dni"])

    _, messages, _ = client.calls[0]
    assert messages[0] == {"role": "system", "content": "Necesito: full_name, dni."}


@pytest.mark.asyncio
async def test_extract_information_fails_closed_for_unaccounted_required_fields() -> None:
    client = _StubClient('{"fields": {}, "missing_fields": []}')
    provider = _make_provider(client)

    result = await provider.extract_information("hola", required_fields=["dni"])

    assert result.missing_fields == ["dni"]


@pytest.mark.asyncio
async def test_extract_information_raises_on_malformed_json() -> None:
    client = _StubClient("nope")
    provider = _make_provider(client)

    with pytest.raises(LLMInvalidResponseError):
        await provider.extract_information("hola", required_fields=["dni"])


@pytest.mark.asyncio
async def test_generate_response_returns_the_raw_model_text() -> None:
    client = _StubClient("¡Hola! ¿En qué puedo ayudarte?")
    provider = _make_provider(client)

    result = await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )

    assert result == "¡Hola! ¿En qué puedo ayudarte?"


@pytest.mark.asyncio
async def test_generate_response_substitutes_intent_and_collected_data_into_the_prompt() -> None:
    client = _StubClient("ok")
    provider = _make_provider(
        client, generate_response_prompt="Intención: {intent}. Datos: {collected_data}."
    )

    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1", intent="appointment", collected_data={"dni": "30111222"}
        )
    )

    _, messages, _ = client.calls[0]
    assert messages[0] == {
        "role": "system",
        "content": "Intención: appointment. Datos: {'dni': '30111222'}.",
    }


@pytest.mark.asyncio
async def test_generate_response_forwards_recent_messages_as_real_chat_history() -> None:
    # Regression, seen live: two consecutive LLM-generated replies both
    # opened with "Hola" because the model had no visibility into what it
    # (or the patient) had just said — `messages` used to be system-only.
    client = _StubClient("ok")
    provider = _make_provider(client)
    recent_messages = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola! Como estas?"},
        {"role": "user", "content": "No, puedo elegir otra cosa?"},
    ]

    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1",
            intent="unknown",
            collected_data={},
            recent_messages=recent_messages,
        )
    )

    _, messages, _ = client.calls[0]
    assert messages[1:] == recent_messages


@pytest.mark.asyncio
async def test_generate_response_includes_contact_memory_in_the_system_prompt() -> None:
    client = _StubClient("ok")
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1",
            intent="unknown",
            collected_data={},
            contact_memory="Paciente frecuente, prefiere turnos por la tarde.",
        )
    )

    _, messages, _ = client.calls[0]
    assert "Paciente frecuente, prefiere turnos por la tarde." in messages[0]["content"]


@pytest.mark.asyncio
async def test_generate_response_omits_contact_memory_line_when_absent() -> None:
    client = _StubClient("ok")
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )

    _, messages, _ = client.calls[0]
    assert "Lo que ya sabemos" not in messages[0]["content"]
