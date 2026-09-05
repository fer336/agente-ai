from app.domain.entities.message import Message
from app.domain.repositories.llm_provider import ExtractionResult, IntentResult, ResponseContext

_APPOINTMENT_KEYWORDS = ("turno", "cita")
_INSURANCE_KEYWORDS = ("obra social", "prepaga", "convenio", "cobertura", "osde")
_SPECIALTY_KEYWORDS = ("especialidad", "especialidades")
#: PRD.md §22's automatic-handoff example phrases, lowercased substrings.
_HANDOFF_KEYWORDS = (
    "llegar tarde",
    "llegando",
    "hablar con",
    "hablar con una persona",
    "administracion",
    "administración",
    "me equivoque",
    "me equivoqué",
    "problema con mi turno",
    "no aparece mi turno",
)


class FakeLLMProvider:
    """In-memory fake implementing `LLMProvider` for local dev and tests.

    Keyword-based, not a real classifier — same "usable placeholder" spirit
    as every other Fake in this codebase (e.g. `FakeDentalinkGateway`
    actually stores/returns data rather than no-op'ing), so the graph can be
    exercised end to end without a real LLM. Swap point for a real provider
    is `app.api.dependencies.gateways.get_llm_provider`.
    """

    async def classify_intent(self, message: str, context: dict[str, object]) -> IntentResult:
        lowered = message.lower()
        if any(keyword in lowered for keyword in _HANDOFF_KEYWORDS):
            return IntentResult(intent="handoff", confidence=0.9)
        if any(keyword in lowered for keyword in _INSURANCE_KEYWORDS):
            return IntentResult(intent="insurance", confidence=0.9)
        if any(keyword in lowered for keyword in _SPECIALTY_KEYWORDS):
            return IntentResult(intent="specialties", confidence=0.9)
        if any(keyword in lowered for keyword in _APPOINTMENT_KEYWORDS):
            return IntentResult(intent="appointment", confidence=0.9)
        return IntentResult(intent="unknown", confidence=0.0)

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult:
        return ExtractionResult(fields={}, missing_fields=list(required_fields))

    async def generate_response(self, context: ResponseContext) -> str:
        return f"[fake-response for intent={context.intent}]"

    async def summarize(self, previous_summary: str, new_messages: list[Message]) -> str:
        new_text = " | ".join(message.text for message in new_messages if message.text)
        if not previous_summary:
            return new_text
        if not new_text:
            return previous_summary
        return f"{previous_summary} | {new_text}"
