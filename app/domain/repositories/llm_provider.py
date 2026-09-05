from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.entities.message import Message


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
    #: Conversational-memory module's bounded context (no PRD.md section
    #: number — this session's own brief) — populated by
    #: `MemoryService.build_response_context`, empty/`None` for any call
    #: site that doesn't go through it yet.
    recent_messages: list[dict[str, str]] = field(default_factory=list)
    contact_memory: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Port to the external LLM used for intent classification, extraction and NLG."""

    async def classify_intent(self, message: str, context: dict[str, object]) -> IntentResult: ...

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult: ...

    async def generate_response(self, context: ResponseContext) -> str: ...

    async def summarize(self, previous_summary: str, new_messages: list[Message]) -> str:
        """Folds `new_messages` into `previous_summary`, producing an
        updated running summary of the contact — conversational-memory
        module's incremental compaction step, see
        `MemoryService.compact`.
        """
        ...
