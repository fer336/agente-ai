import pytest

from app.application.errors.error_types import (
    INVALID_LLM_OUTPUT,
    LLM_AUTH_ERROR,
    LLM_ERROR,
    LLM_QUOTA_EXCEEDED,
    OPENAI_TIMEOUT,
)
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import (
    LLMAuthError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMQuotaExceededError,
    LLMTimeoutError,
)
from app.infrastructure.llm.openai_compatible_llm_provider import (
    DEFAULT_CLASSIFY_INTENT_PROMPT,
    DEFAULT_EXTRACT_INFORMATION_PROMPT,
    DEFAULT_GENERATE_RESPONSE_PROMPT,
    OpenAICompatibleLLMProvider,
    _error_type_of,
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
async def test_understand_accepts_the_location_intent_label() -> None:
    # T3 (free-text menu-intents parity): "location" was added to
    # `_UNDERSTANDING_LABELS`/`DEFAULT_UNDERSTAND_PROMPT` so a phrasing the
    # deterministic `asks_for_location` substring pre-check doesn't catch
    # (e.g. "cómo hago para llegar") still reaches the same deterministic
    # location card a `MENU_LOCATION_PAYLOAD` tap does — via the LLM this
    # time, instead of falling to "question" and getting LLM prose.
    client = _StubClient(
        '{"intent": "location", "confidence": 0.92, "answer": null,'
        ' "specialty_mention": null, "professional_mention": null,'
        ' "operation_mention": null, "navigation_target": null}'
    )
    provider = _make_provider(client)

    result = await provider.understand("cómo hago para llegar", context={})

    assert result.intent == "location"


@pytest.mark.asyncio
async def test_understand_rejects_the_removed_treatment_catalog_intent_label() -> None:
    # The dedicated "treatment_catalog" intent (a fixed, hardcoded
    # treatment/price list) was removed — the clinic owner rejected it as
    # misleading, no real Dentalink data behind it. A model still trained
    # on the old label must not silently route anywhere; "qué tratamientos
    # ofrecen"-type questions now fall under "question" instead.
    client = _StubClient(
        '{"intent": "treatment_catalog", "confidence": 0.9, "answer": null,'
        ' "specialty_mention": null, "professional_mention": null,'
        ' "operation_mention": null}'
    )
    provider = _make_provider(client)

    with pytest.raises(LLMInvalidResponseError):
        await provider.understand("¿qué tratamientos ofrecen?", context={})


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
    assert messages[-len(recent_messages) :] == recent_messages


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
async def test_generate_response_flags_contact_memory_as_possibly_stale() -> None:
    # Regression, seen live: the compaction worker only runs on a periodic
    # sweep, so `contact_memory` can lag behind an action taken earlier in
    # THIS SAME conversation (e.g. a just-cancelled appointment) — the
    # model trusted the stale summary over its own immediately preceding
    # message and told a patient they still had a turno right after
    # cancelling it. The prompt must say this summary can be outdated and
    # subordinate to the live conversation/collected data.
    client = _StubClient("ok")
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1",
            intent="unknown",
            collected_data={},
            contact_memory="Tiene un turno para el 18/09 a las 13:00.",
        )
    )

    _, messages, _ = client.calls[0]
    content = messages[0]["content"]
    assert "desactualizado" in content
    assert "priman siempre" in content


@pytest.mark.asyncio
async def test_generate_response_omits_contact_memory_line_when_absent() -> None:
    client = _StubClient("ok")
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )

    _, messages, _ = client.calls[0]
    assert "sabíamos de este paciente" not in messages[0]["content"]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (LLMAuthError("nope"), LLM_AUTH_ERROR),
        (LLMQuotaExceededError("rate limited"), LLM_QUOTA_EXCEEDED),
        (LLMTimeoutError("timed out"), OPENAI_TIMEOUT),
        (LLMInvalidResponseError("bad json"), INVALID_LLM_OUTPUT),
        (LLMProviderError("something else"), LLM_ERROR),
    ],
)
def test_error_type_of_maps_each_llm_exception(exc: Exception, expected: str) -> None:
    assert _error_type_of(exc) == expected


@pytest.mark.asyncio
async def test_generate_response_forbids_greeting_once_the_conversation_started() -> None:
    client = _StubClient("ok")
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1",
            intent="question",
            collected_data={},
            conversation_started=True,
        )
    )
    await provider.generate_response(
        ResponseContext(
            conversation_id="conv-1",
            intent="question",
            collected_data={},
            conversation_started=False,
        )
    )

    started_prompt = client.calls[0][1][0]["content"]
    first_turn_prompt = client.calls[1][1][0]["content"]
    assert "La conversación ya empezó:" in started_prompt
    assert "La conversación ya empezó:" not in first_turn_prompt


@pytest.mark.asyncio
async def test_understand_forbids_greeting_in_the_answer_once_the_conversation_started() -> None:
    client = _StubClient('{"intent": "question", "confidence": 0.9, "answer": "Sí."}')
    provider = _make_provider(client)

    await provider.understand("¿atienden particulares?", context={"conversation_started": True})
    await provider.understand("¿atienden particulares?", context={"conversation_started": False})

    started_messages = client.calls[0][1]
    first_turn_messages = client.calls[1][1]
    assert any("La conversación ya empezó:" in message["content"] for message in started_messages)
    assert not any(
        "La conversación ya empezó:" in message["content"] for message in first_turn_messages
    )


@pytest.mark.asyncio
async def test_generate_response_honours_a_per_call_temperature() -> None:
    client = _StubClient("ok")
    provider = _make_provider(client, temperature=0.2)

    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="x", collected_data={}, temperature=0.9)
    )
    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="x", collected_data={})
    )

    assert [call[2] for call in client.calls] == [0.9, 0.2]


@pytest.mark.asyncio
async def test_generate_response_always_carries_the_no_premature_action_claim_rule() -> None:
    # Appended outside the admin-editable prompt so a saved version cannot lose it.
    client = _StubClient("ok")
    provider = _make_provider(client, generate_response_prompt="Intención: {intent}.")

    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )

    _, messages, _ = client.calls[0]
    system_text = " ".join(m["content"] for m in messages if m["role"] == "system")
    assert "te lo confirmo" in system_text
    assert "✅ Confirmar" in system_text
    assert "[SYSTEM]" in system_text


@pytest.mark.asyncio
async def test_understand_carries_the_no_premature_action_claim_rule() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.9, "answer": null}')
    provider = _make_provider(client)

    await provider.understand("sí, quiero ese turno", context={})

    _, messages, _ = client.calls[0]
    system_text = " ".join(m["content"] for m in messages if m["role"] == "system")
    assert "te lo confirmo" in system_text
    assert "✅ Confirmar" in system_text
    assert "[SYSTEM]" in system_text


@pytest.mark.asyncio
async def test_generate_response_and_understand_carry_the_no_diagnosis_rule() -> None:
    client = _StubClient('{"intent": "unknown", "confidence": 0.9, "answer": null}')
    provider = _make_provider(client)

    await provider.generate_response(
        ResponseContext(conversation_id="conv-1", intent="unknown", collected_data={})
    )
    await provider.understand("me duele una muela, ¿qué tengo?", context={})

    for _, messages, _ in client.calls:
        system_text = " ".join(m["content"] for m in messages if m["role"] == "system")
        assert "diagnóstic" in system_text
        assert "caries" in system_text
        assert "profesional" in system_text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"handoff_offer": true', True),
        ('"handoff_offer": false', False),
        ('"handoff_offer": null', False),
        ('"handoff_offer": "true"', False),
        ('"other": 1', False),
    ],
)
async def test_understand_parses_the_boolean_handoff_offer_flag(raw, expected) -> None:
    client = _StubClient(
        '{"intent": "question", "confidence": 0.9, "answer": "¿Te paso con administración?", '
        + raw
        + "}"
    )
    provider = _make_provider(client)

    result = await provider.understand("¿aceptan obra social?", context={})

    assert result.handoff_offer is expected


@pytest.mark.asyncio
async def test_understand_accepts_the_faq_topic_label() -> None:
    client = _StubClient(
        '{"intent": "faq_topic", "confidence": 0.9, "answer": null,'
        ' "specialty_mention": null, "professional_mention": null,'
        ' "operation_mention": null, "navigation_target": null}'
    )
    provider = _make_provider(client)

    result = await provider.understand("cuánto sale el blanqueamiento", context={})

    assert result.intent == "faq_topic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"faq_topic_id": "blanqueamiento"', "blanqueamiento"),
        ('"faq_topic_id": "consulta_particular"', "consulta_particular"),
        ('"faq_topic_id": " alineadores "', "alineadores"),
        ('"faq_topic_id": "ortodoncia"', None),
        ('"faq_topic_id": ""', None),
        ('"faq_topic_id": null', None),
        ('"faq_topic_id": 3', None),
        ('"faq_topic_id": ["blanqueamiento"]', None),
        ('"faq_topic_id": true', None),
        ('"other": 1', None),
    ],
)
async def test_understand_parses_and_validates_the_faq_topic_id(raw, expected) -> None:
    client = _StubClient('{"intent": "faq_topic", "confidence": 0.9, "answer": null, ' + raw + "}")
    provider = _make_provider(client)

    result = await provider.understand("cuánto me sale aclararme los dientes", context={})

    assert result.intent == "faq_topic"
    assert result.faq_topic_id == expected


def test_the_understand_prompt_documents_the_faq_topic_id_and_the_five_ids() -> None:
    from app.agent.clinic_topics import CLINIC_TOPICS
    from app.infrastructure.llm.openai_compatible_llm_provider import DEFAULT_UNDERSTAND_PROMPT

    assert '"faq_topic_id"' in DEFAULT_UNDERSTAND_PROMPT
    for topic in CLINIC_TOPICS:
        assert topic.id in DEFAULT_UNDERSTAND_PROMPT
    assert "null" in DEFAULT_UNDERSTAND_PROMPT.split('- "faq_topic_id":')[1].split("\n- ")[0]


def test_the_understand_prompt_routes_priced_topics_to_faq_topic_not_question() -> None:
    from app.infrastructure.llm.openai_compatible_llm_provider import DEFAULT_UNDERSTAND_PROMPT

    assert "faq_topic" in DEFAULT_UNDERSTAND_PROMPT
    question_definition = DEFAULT_UNDERSTAND_PROMPT.split("- question:")[1].split("- unknown:")[0]
    for claimed in ("blanqueamiento", "limpieza", "alineadores"):
        assert claimed not in question_definition


def test_the_understand_prompt_sends_payments_to_administration_without_conflicts() -> None:
    from app.infrastructure.llm.openai_compatible_llm_provider import DEFAULT_UNDERSTAND_PROMPT

    faq_definition = DEFAULT_UNDERSTAND_PROMPT.split("- faq_topic:")[1].split("- question:")[0]
    question_definition = DEFAULT_UNDERSTAND_PROMPT.split("- question:")[1].split("- unknown:")[0]
    assert "forma de pago" not in faq_definition
    assert "formas de pago" not in question_definition
    assert "Administración" in question_definition
    assert "anticipos" in question_definition
    assert "handoff_offer en true" in question_definition


@pytest.mark.asyncio
async def test_understand_accepts_the_thanks_label() -> None:
    client = _StubClient('{"intent": "thanks", "confidence": 0.93}')
    provider = _make_provider(client)

    result = await provider.understand("muchísimas gracias por todo", context={})

    assert result.intent == "thanks"
    assert result.confidence == 0.93
    assert result.answer is None


def test_understand_prompt_describes_the_thanks_label_and_lists_it_in_the_contract() -> None:
    from app.infrastructure.llm.openai_compatible_llm_provider import DEFAULT_UNDERSTAND_PROMPT

    assert "thanks" in DEFAULT_UNDERSTAND_PROMPT.split("una de:")[1].split(">")[0]
    assert "- thanks:" in DEFAULT_UNDERSTAND_PROMPT
    assert "sin pedir nada" in DEFAULT_UNDERSTAND_PROMPT
