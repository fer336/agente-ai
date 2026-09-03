import pytest

from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import LLMInvalidResponseError
from app.infrastructure.llm.openai_compatible_llm_provider import OpenAICompatibleLLMProvider


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


@pytest.mark.asyncio
async def test_classify_intent_parses_the_models_json_response() -> None:
    client = _StubClient('{"intent": "appointment", "confidence": 0.87}')
    provider = OpenAICompatibleLLMProvider(client, "gemini/gemini-3.7-flash")  # type: ignore[arg-type]

    result = await provider.classify_intent("quiero un turno", context={})

    assert result.intent == "appointment"
    assert result.confidence == 0.87
    model, messages, _ = client.calls[0]
    assert model == "gemini/gemini-3.7-flash"
    assert messages[-1] == {"role": "user", "content": "quiero un turno"}


@pytest.mark.asyncio
async def test_classify_intent_includes_recent_messages_and_contact_memory_when_present() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.1}')
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

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
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    with pytest.raises(LLMInvalidResponseError):
        await provider.classify_intent("hola", context={})


@pytest.mark.asyncio
async def test_classify_intent_raises_on_unrecognized_intent_label() -> None:
    client = _StubClient('{"intent": "made_up_label", "confidence": 0.9}')
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    with pytest.raises(LLMInvalidResponseError):
        await provider.classify_intent("hola", context={})


@pytest.mark.asyncio
async def test_extract_information_parses_fields_and_missing_fields() -> None:
    client = _StubClient(
        '{"fields": {"full_name": "Juan Perez"}, "missing_fields": ["dni"]}'
    )
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    result = await provider.extract_information(
        "me llamo Juan Perez", required_fields=["full_name", "dni"]
    )

    assert result.fields == {"full_name": "Juan Perez"}
    assert result.missing_fields == ["dni"]


@pytest.mark.asyncio
async def test_extract_information_fails_closed_for_unaccounted_required_fields() -> None:
    client = _StubClient('{"fields": {}, "missing_fields": []}')
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    result = await provider.extract_information("hola", required_fields=["dni"])

    assert result.missing_fields == ["dni"]


@pytest.mark.asyncio
async def test_extract_information_raises_on_malformed_json() -> None:
    client = _StubClient("nope")
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    with pytest.raises(LLMInvalidResponseError):
        await provider.extract_information("hola", required_fields=["dni"])


@pytest.mark.asyncio
async def test_generate_response_returns_the_raw_model_text() -> None:
    client = _StubClient("¡Hola! ¿En qué puedo ayudarte?")
    provider = OpenAICompatibleLLMProvider(client, "model")  # type: ignore[arg-type]

    result = await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )

    assert result == "¡Hola! ¿En qué puedo ayudarte?"
