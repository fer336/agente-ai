from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Outcome of classifying a user message's intent."""

    intent: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Outcome of extracting structured fields from a user message."""

    fields: dict[str, object]
    missing_fields: list[str]


@dataclass(frozen=True, slots=True)
class ResponseContext:
    """Context passed to the LLM to generate a natural-language response."""

    conversation_id: str
    intent: str
    collected_data: dict[str, object]


@runtime_checkable
class LLMProvider(Protocol):
    """Port to the external LLM used for intent classification, extraction and NLG."""

    async def classify_intent(self, message: str, context: dict[str, object]) -> IntentResult: ...

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult: ...

    async def generate_response(self, context: ResponseContext) -> str: ...
