from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.entities.message import Message


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Outcome of classifying a user message's intent."""

    intent: str
    confidence: float


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    """One LLM pass over a patient's turn: what they want, what they named,
    and — when the graph has no operation for it — the answer itself.

    Replaces classify-then-guess: the same call that decides the intent
    also reports the specialty/professional/operation the patient
    mentioned, so an operational flow can be entered already populated
    instead of walking the patient back through a menu they already
    answered in prose ("quiero un turno con ortodoncia").

    The mentions are deliberately RAW patient wording, never ids: the LLM
    reports what was said, and the graph resolves it against the real
    Dentalink catalog (`resolve_by_name`). The model never invents an id.
    """

    intent: str
    confidence: float
    #: Set only for a question the graph has no operation for ("¿atienden
    #: los sábados?"). The patient gets this instead of the menu.
    answer: str | None = None
    specialty_mention: str | None = None
    professional_mention: str | None = None
    #: One of "create" / "reschedule" / "cancel" when the patient said so
    #: outright ("quiero cancelar mi turno"), else `None`.
    operation_mention: str | None = None


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

    async def understand(self, message: str, context: dict[str, object]) -> UnderstandingResult:
        """Richer counterpart to `classify_intent` — see `UnderstandingResult`.

        Kept alongside `classify_intent` rather than replacing it because
        the two answer different questions: this one drives the live
        conversation, that one stays the narrow, cheap classifier the eval
        suite and any future batch job can rely on.
        """
        ...

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
