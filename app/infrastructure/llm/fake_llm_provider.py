import re

from app.domain.entities.message import Message
from app.domain.repositories.llm_provider import (
    ExtractionResult,
    IntentResult,
    ResponseContext,
    UnderstandingResult,
)

#: `create_fallback_node`'s LLM-generated wording, faked here with fixed
#: variety keyed by `intentos_seguidos_sin_resolver` — same "usable
#: placeholder" spirit as this class's keyword-based `classify_intent`,
#: rather than a single repeated string, so local/dev exercises the same
#: "never say it twice, escalate on repeat" behavior a real LLM would give.
_FALLBACK_MESSAGES = (
    "Che, no llegué a entender bien eso último. Me marcás una de estas opciones?",
    "Mmm, no me quedó claro qué necesitás. Fijate si alguna de estas te sirve.",
)
_FALLBACK_MESSAGE_REPEATED = (
    "Veo que venimos yendo y viniendo con esto. Querés que te pase directo con administración?"
)

#: `create_appointment_node`'s identification-stage retry prompts — same
#: varied-wording spirit as the fallback messages above.
_IDENTIFICATION_RETRY_MESSAGES = (
    "No logré separar bien tu nombre del DNI ahí. Me lo escribís junto, tipo Juan Pérez, 30123456?",
    "Sigo sin poder leerlo bien. Probá escribiendo primero tu nombre completo y "
    "después tu DNI, todo en un mismo mensaje: Juan Pérez, 30123456.",
)
_DNI_INVALID_MESSAGES = (
    "Ese DNI no me cierra el número. Pasame solo los dígitos, 7 u 8 en total, ejemplo: 30123456.",
    "Todavía no es un DNI válido. Escribime nada más los números, sin puntos ni "
    "espacios, ejemplo: 30123456.",
)

#: `extract_information`'s "nombre_completo" field, faked heuristically
#: (real word here, not a full classifier): words that never appear in a
#: real full name but commonly appear in ordinary chatter, so a message
#: like "hola quiero un turno" isn't mistaken for a name. Deliberately
#: small and Spanish-specific — same "usable placeholder" spirit as this
#: class's other keyword-based methods; the real provider judges this with
#: an actual LLM call instead (see `app.agent.nodes.appointment.
#: _extract_full_name`, which this fake's behavior must satisfy the same
#: two live-found cases for: accept a real name-first answer like "Pedro
#: Cassera", reject ordinary chatter like "Bien vos?").
_NON_NAME_WORDS = frozenset(
    {
        "hola",
        "buenas",
        "buenos",
        "dias",
        "días",
        "tardes",
        "noches",
        "bien",
        "vos",
        "todo",
        "quiero",
        "queria",
        "quería",
        "querria",
        "querría",
        "quisiera",
        "necesito",
        "turno",
        "turnos",
        "cita",
        "consulta",
        "gracias",
        "porfavor",
        "porfa",
        "ayuda",
        "informacion",
        "información",
        "saber",
        "como",
        "cómo",
        "cuando",
        "cuándo",
        "donde",
        "dónde",
        "que",
        "qué",
        "hacer",
        "sacar",
        "reservar",
        "cancelar",
        "reagendar",
        "administracion",
        "administración",
        "hablar",
        "persona",
        "humano",
        "no",
        "si",
        "sé",
        "se",
        "estoy",
        "soy",
        "registrado",
        "registrada",
        "creo",
        "puedo",
        "podes",
        "podés",
        "puede",
    }
)

_DNI_EXTRACT_PATTERN = re.compile(r"\d{7,8}")


def _looks_like_a_name(text: str) -> bool:
    words = text.casefold().split()
    return bool(words) and not any(word.strip(".,!?¡¿") in _NON_NAME_WORDS for word in words)


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

    async def understand(self, message: str, context: dict[str, object]) -> UnderstandingResult:
        """Keyword-based like `classify_intent`, plus the mentions the real
        provider extracts — enough for the graph to be exercised end to end
        without a live model."""
        lowered = message.lower()
        intent_result = await self.classify_intent(message, context)

        operation = None
        if any(word in lowered for word in ("cancelar", "anular")):
            operation = "cancel"
        elif any(word in lowered for word in ("reagendar", "cambiar", "reprogramar")):
            operation = "reschedule"
        elif any(word in lowered for word in _APPOINTMENT_KEYWORDS):
            operation = "create"

        return UnderstandingResult(
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            answer=None,
            specialty_mention=None,
            professional_mention=None,
            operation_mention=operation,
        )

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult:
        fields: dict[str, object] = {}
        missing: list[str] = []
        for field in required_fields:
            if field == "nombre_completo":
                stripped = message.strip()
                if stripped and _looks_like_a_name(stripped):
                    fields[field] = stripped
                else:
                    missing.append(field)
            elif field == "dni":
                match = _DNI_EXTRACT_PATTERN.search(message)
                if match is not None:
                    fields[field] = match.group(0)
                else:
                    missing.append(field)
            else:
                missing.append(field)
        return ExtractionResult(fields=fields, missing_fields=missing)

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
