from app.domain.repositories.llm_provider import ExtractionResult, IntentResult, ResponseContext

_APPOINTMENT_KEYWORDS = ("turno", "cita")


class FakeLLMProvider:
    """In-memory fake implementing `LLMProvider` for local dev and tests."""

    async def classify_intent(self, message: str, context: dict[str, object]) -> IntentResult:
        lowered = message.lower()
        if any(keyword in lowered for keyword in _APPOINTMENT_KEYWORDS):
            return IntentResult(intent="book_appointment", confidence=0.9)
        return IntentResult(intent="unknown", confidence=0.0)

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult:
        return ExtractionResult(fields={}, missing_fields=list(required_fields))

    async def generate_response(self, context: ResponseContext) -> str:
        return f"[fake-response for intent={context.intent}]"
