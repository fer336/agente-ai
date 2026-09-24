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

#: `resolve_interaction.py`'s `POST_ACTION_CLOSE_INTENT` — faked per
#: `accion_completada` (the same key that node passes in `collected_data`),
#: same "usable placeholder" spirit as this class's other keyword-based
#: replies.
_POST_ACTION_CLOSE_MESSAGES = {
    "create_appointment": "De nada! Ahí quedó anotado tu turno, te esperamos.",
    "reschedule_appointment": "De nada! Ya quedó reagendado, nos vemos pronto.",
    "cancel_appointment": "Listo, quedó cancelado. Cualquier cosa, escribime.",
}
_POST_ACTION_CLOSE_DEFAULT_MESSAGE = "De nada! Cualquier otra cosa, decime."

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
#: Checked BEFORE the generic `_APPOINTMENT_KEYWORDS` fallback below — seen
#: live: "Qué turnos tengo?" contains "turno" too, so without this it was
#: read as a CREATE mention instead of a query about existing appointments.
_VIEW_APPOINTMENT_KEYWORDS = (
    "que turno",
    "qué turno",
    "mis turnos",
    "mi turno",
    "tengo turno",
    "turnos tengo",
)
_INSURANCE_KEYWORDS = ("obra social", "prepaga", "convenio", "cobertura", "osde")
_SPECIALTY_KEYWORDS = ("especialidad", "especialidades")
#: T3 (free-text menu-intents parity): phrasings the deterministic
#: `asks_for_location` substring pre-check (`app.agent.nodes.location`)
#: does NOT already catch on its own — e.g. it matches "cómo llegar" but
#: not "cómo hago para llegar" (extra words in between). These exist so a
#: parity test can exercise the LLM-`understand`-based "location" label
#: end to end, distinct from the deterministic fast path.
_LOCATION_UNDERSTANDING_KEYWORDS = (
    "como hago para llegar",
    "cómo hago para llegar",
    "donde los encuentro",
    "dónde los encuentro",
)
#: T3: "volver al menú principal"-shaped free text — the fake's own
#: equivalent of the real `navigation_target` field ("main" case only; the
#: other targets — specialty/professional/slot — aren't reachable from a
#: bare keyword the way "main" is, since they need workflow context this
#: fake doesn't model).
_NAVIGATION_MAIN_KEYWORDS = (
    "menu principal",
    "menú principal",
    "volver al menu",
    "volver al menú",
    "volver al inicio",
    "empezar de nuevo",
)
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
        # T4 (R3-fake-classify-intent-diverges-from-real-labels): "location"
        # is deliberately NOT one of this method's possible outcomes — the
        # real provider's `_INTENT_LABELS` (the narrow allowlist this
        # method's own real-provider counterpart validates against) never
        # includes it, only the separate, richer `_UNDERSTANDING_LABELS`
        # does (T3). `understand()` below still recognizes the same
        # keywords; this method must not diverge from what the real
        # provider's `classify_intent` can actually return.
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
        # "location" is checked here, not inside `classify_intent` (see that
        # method's own comment) — this is the ONLY place this fake ever
        # reports it, matching the real provider's `understand`-only label.
        if any(keyword in lowered for keyword in _LOCATION_UNDERSTANDING_KEYWORDS):
            intent = "location"
            confidence = 0.9
        else:
            intent_result = await self.classify_intent(message, context)
            intent = intent_result.intent
            confidence = intent_result.confidence

        operation = None
        if any(word in lowered for word in ("cancelar", "anular")):
            operation = "cancel"
        elif any(word in lowered for word in ("reagendar", "cambiar", "reprogramar")):
            operation = "reschedule"
        elif any(word in lowered for word in _VIEW_APPOINTMENT_KEYWORDS):
            operation = "view"
        elif any(word in lowered for word in _APPOINTMENT_KEYWORDS):
            operation = "create"

        navigation_target = None
        if any(keyword in lowered for keyword in _NAVIGATION_MAIN_KEYWORDS):
            navigation_target = "main"
            if confidence < 0.5:
                # `resolve_interaction.py` only honours a navigation
                # request from IDLE (no active stage) through the generic
                # confidence-gated path below `_MIN_INTENT_CONFIDENCE` —
                # mid-flow it's read unconditionally instead, straight off
                # `result.navigation_target` — so this forced confidence
                # only ever matters for the idle case; "appointment" is the
                # same intent a real MENU_MAIN_PAYLOAD tap resolves to.
                intent = "appointment"
                confidence = 0.9

        return UnderstandingResult(
            intent=intent,
            confidence=confidence,
            answer=None,
            specialty_mention=None,
            professional_mention=None,
            operation_mention=operation,
            navigation_target=navigation_target,
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
        if context.intent == "post_action_close":
            action = context.collected_data.get("accion_completada")
            return _POST_ACTION_CLOSE_MESSAGES.get(str(action), _POST_ACTION_CLOSE_DEFAULT_MESSAGE)
        # Several call sites (`appointment.py`'s propose_*_confirmation/
        # cancel_success/no_professionals, `agreement.py`'s agreement_found,
        # ...) pass a real name along in `collected_data` for the model to
        # weave into the sentence, and more than one can be present on the
        # same call (e.g. both `profesional` and `nombre_paciente`) — echo
        # every one that's set, rather than only the first match, so a test
        # asserting any of them reached the LLM call doesn't need its own
        # bespoke Fake branch.
        echoed = [
            str(context.collected_data[key])
            for key in ("profesional", "convenio", "nombre_paciente")
            if context.collected_data.get(key) is not None
        ]
        if echoed:
            return f"[fake-response for intent={context.intent}] con {' y '.join(echoed)}"
        return f"[fake-response for intent={context.intent}]"

    async def summarize(self, previous_summary: str, new_messages: list[Message]) -> str:
        new_text = " | ".join(message.text for message in new_messages if message.text)
        if not previous_summary:
            return new_text
        if not new_text:
            return previous_summary
        return f"{previous_summary} | {new_text}"
