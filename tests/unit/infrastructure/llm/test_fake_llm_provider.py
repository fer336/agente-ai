import pytest

from app.domain.repositories.llm_provider import (
    ExtractionResult,
    IntentResult,
    LLMProvider,
    ResponseContext,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.gateways import make_llm_provider


@pytest.mark.asyncio
async def test_classify_intent_recognizes_appointment_keyword():
    provider = make_llm_provider()

    result = await provider.classify_intent("Quiero pedir un turno", context={})

    assert result == IntentResult(intent="book_appointment", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_intent_returns_unknown_for_unrecognized_message():
    provider = make_llm_provider()

    result = await provider.classify_intent("Hola, buen día", context={})

    assert result == IntentResult(intent="unknown", confidence=0.0)


@pytest.mark.asyncio
async def test_extract_information_reports_all_requested_fields_as_missing():
    provider = make_llm_provider()

    result = await provider.extract_information(
        "Quiero un turno", required_fields=["specialty", "date"]
    )

    assert result == ExtractionResult(fields={}, missing_fields=["specialty", "date"])


@pytest.mark.asyncio
async def test_generate_response_includes_the_intent_from_context():
    provider = make_llm_provider()
    context = ResponseContext(
        conversation_id="conv-1", intent="book_appointment", collected_data={}
    )

    response = await provider.generate_response(context)

    assert response == "[fake-response for intent=book_appointment]"


def test_fake_llm_provider_satisfies_llm_provider_protocol():
    assert isinstance(FakeLLMProvider(), LLMProvider)
