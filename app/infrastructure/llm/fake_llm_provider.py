from app.domain.entities.message import Message
from app.domain.repositories.llm_provider import ExtractionResult, IntentResult, ResponseContext

#: `create_fallback_node`'s LLM-generated wording, faked here with fixed
#: variety keyed by `intentos_seguidos_sin_resolver` — same "usable
#: placeholder" spirit as this class's keyword-based `classify_intent`,
#: rather than a single repeated string, so local/dev exercises the same
#: "never say it twice, escalate on repeat" behavior a real LLM would give.
_FALLBACK_MESSAGES = (
    "Che, no llegué a entender bien eso último. ¿Me marcás una de estas opciones?",
    "Mmm, no me quedó claro qué necesitás. Fijate si alguna de estas te sirve.",
)
_FALLBACK_MESSAGE_REPEATED = (
    "Veo que venimos yendo y viniendo con esto. ¿Querés que te pase directo con "
    "administración?"
)

#: `create_appointment_node`'s identification-stage retry prompts — same
#: varied-wording spirit as the fallback messages above.
_IDENTIFICATION_RETRY_MESSAGES = (
    "No logré separar bien tu nombre del DNI ahí. ¿Me lo escribís junto, tipo "
    "Juan Pérez, 30123456?",
    "Sigo sin poder leerlo bien. Probá escribiendo primero tu nombre completo y "
    "después tu DNI, todo en un mismo mensaje: Juan Pérez, 30123456.",
)
_DNI_INVALID_MESSAGES = (
    "Ese DNI no me cierra el número. Pasame solo los dígitos, 7 u 8 en total, "
    "ejemplo: 30123456.",
    "Todavía no es un DNI válido. Escribime nada más los números, sin puntos ni "
    "espacios, ejemplo: 30123456.",
)

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
        if context.intent == "fallback":
            raw_attempts = context.collected_data.get("intentos_seguidos_sin_resolver", 1)
            attempts = raw_attempts if isinstance(raw_attempts, int) else 1
            if attempts >= 2:
                return _FALLBACK_MESSAGE_REPEATED
            return _FALLBACK_MESSAGES[(attempts - 1) % len(_FALLBACK_MESSAGES)]
        if context.intent in ("identification_retry", "dni_invalid"):
            raw_attempts = context.collected_data.get("intentos_seguidos", 1)
            attempts = raw_attempts if isinstance(raw_attempts, int) else 1
            messages = (
                _IDENTIFICATION_RETRY_MESSAGES
                if context.intent == "identification_retry"
                else _DNI_INVALID_MESSAGES
            )
            return messages[(attempts - 1) % len(messages)]
        return f"[fake-response for intent={context.intent}]"

    async def summarize(self, previous_summary: str, new_messages: list[Message]) -> str:
        new_text = " | ".join(message.text for message in new_messages if message.text)
        if not previous_summary:
            return new_text
        if not new_text:
            return previous_summary
        return f"{previous_summary} | {new_text}"
