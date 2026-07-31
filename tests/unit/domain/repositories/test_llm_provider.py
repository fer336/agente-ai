from app.domain.repositories.llm_provider import (
    ExtractionResult,
    IntentResult,
    LLMProvider,
    ResponseContext,
)


def test_creates_intent_result_with_intent_and_confidence():
    result = IntentResult(intent="book_appointment", confidence=0.92)

    assert result.intent == "book_appointment"
    assert result.confidence == 0.92


def test_creates_extraction_result_with_fields_and_missing_fields():
    result = ExtractionResult(
        fields={"specialty": "cleaning"},
        missing_fields=["preferred_date"],
    )

    assert result.fields == {"specialty": "cleaning"}
    assert result.missing_fields == ["preferred_date"]


def test_creates_response_context_with_conversation_data():
    context = ResponseContext(
        conversation_id="conv-1",
        intent="book_appointment",
        collected_data={"specialty": "cleaning"},
    )

    assert context.conversation_id == "conv-1"
    assert context.intent == "book_appointment"
    assert context.collected_data == {"specialty": "cleaning"}


def test_conforming_class_satisfies_llm_provider_protocol():
    class ConformingLLMProvider:
        async def classify_intent(self, message, context):
            return IntentResult(intent="unknown", confidence=0.0)

        async def extract_information(self, message, required_fields):
            return ExtractionResult(fields={}, missing_fields=list(required_fields))

        async def generate_response(self, context):
            return "ok"

    assert isinstance(ConformingLLMProvider(), LLMProvider)


def test_partial_class_does_not_satisfy_llm_provider_protocol():
    class PartialLLMProvider:
        async def classify_intent(self, message, context):
            return IntentResult(intent="unknown", confidence=0.0)

    assert not isinstance(PartialLLMProvider(), LLMProvider)
