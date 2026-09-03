import json

from app.application.errors.error_types import (
    INVALID_LLM_OUTPUT,
    LLM_AUTH_ERROR,
    LLM_ERROR,
    OPENAI_TIMEOUT,
)
from app.domain.repositories.llm_provider import ExtractionResult, IntentResult, ResponseContext
from app.infrastructure.llm.client import OpenAICompatibleLLMClient
from app.infrastructure.llm.exceptions import (
    LLMAuthError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "llm"

#: Kept in sync with the welcome menu's payload->intent contract
#: (`app.agent.nodes.resolve_interaction._MENU_BUTTON_INTENTS`) and
#: `graph.py`'s routing — a label outside this set would route nowhere.
_INTENT_LABELS = ("appointment", "insurance", "specialties", "handoff", "unknown")

#: First-pass prompt, not yet tuned against real patient phrasing (see
#: this session's decision to hold off on deeper classifier tuning until
#: a Dentalink token and real conversation samples exist) — good enough to
#: exercise the real gateway end to end, expected to be revised.
_CLASSIFY_SYSTEM_PROMPT = f"""Sos un clasificador de intención para el asistente de WhatsApp \
de una clínica dental en Argentina.

Dado el mensaje del paciente (y el contexto reciente si lo hay), devolvé SOLO un JSON con \
esta forma exacta, sin texto adicional:
{{"intent": "<una de: {", ".join(_INTENT_LABELS)}>", "confidence": <0.0 a 1.0>}}

- appointment: pedir, cambiar o cancelar un turno.
- insurance: preguntar por obra social, prepaga o convenios.
- specialties: preguntar qué especialidades atiende la clínica.
- handoff: pedir hablar con una persona, urgencias, reclamos, quejas, o cualquier cosa que \
un bot no debería resolver solo.
- unknown: cualquier otra cosa, saludos, o si no estás seguro.
"""


def _http_status_of(exc: Exception) -> str | None:
    if hasattr(exc, "status_code"):
        return str(exc.status_code)
    return None


def _error_type_of(exc: Exception) -> str:
    if isinstance(exc, LLMAuthError):
        return LLM_AUTH_ERROR
    if isinstance(exc, LLMTimeoutError):
        return OPENAI_TIMEOUT
    if isinstance(exc, LLMInvalidResponseError):
        return INVALID_LLM_OUTPUT
    return LLM_ERROR


class OpenAICompatibleLLMProvider:
    """`OpenAICompatibleLLMClient`-based real implementation of `LLMProvider`.

    Every method raises a typed `LLMProviderError` subclass on an actual
    gateway failure (network/timeout/auth/malformed HTTP response) or on
    the model returning text that isn't the JSON shape the prompt asked
    for — never silently degrades a real failure into a fake "unknown"
    result, matching this codebase's fail-closed gateway convention
    (`DentalinkClient`/`YCloudClient`). The caller's node is already
    wrapped by `with_error_handling`, which routes any raised exception to
    `handle_error` and records it — that is the intended recovery path,
    not a local try/except here.
    """

    def __init__(self, client: OpenAICompatibleLLMClient, model: str) -> None:
        self._client = client
        self._model = model

    async def classify_intent(self, message: str, context: dict[str, object]) -> IntentResult:
        messages = [{"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT}]
        recent_messages = context.get("recent_messages")
        if recent_messages:
            messages.append(
                {"role": "system", "content": f"Contexto reciente: {recent_messages}"}
            )
        contact_memory = context.get("contact_memory")
        if contact_memory:
            messages.append(
                {"role": "system", "content": f"Resumen del contacto: {contact_memory}"}
            )
        messages.append({"role": "user", "content": message})

        async def _call() -> IntentResult:
            content = await self._client.chat_completion(self._model, messages)
            return _parse_intent_result(content)

        return await traced_call(
            tool_name="ClassifyIntentTool",
            provider=_PROVIDER,
            operation="classify_intent",
            # `message` itself is never included — a patient's free-text
            # message can carry PII (PRD.md §41's "sin información sensible
            # innecesaria"), same guardrail every other traced gateway call
            # in this codebase already follows.
            request_summary=f"message_length={len(message)}",
            call=_call,
            response_summary=lambda result: f"intent={result.intent} conf={result.confidence}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def extract_information(
        self, message: str, required_fields: list[str]
    ) -> ExtractionResult:
        prompt = (
            "Extraé los siguientes campos del mensaje del paciente, devolviendo SOLO un JSON "
            f'con la forma {{"fields": {{...}}, "missing_fields": [...]}}. Campos requeridos: '
            f"{', '.join(required_fields)}. Un campo que no aparece en el mensaje va en "
            '"missing_fields", no lo inventes.'
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message},
        ]

        async def _call() -> ExtractionResult:
            content = await self._client.chat_completion(self._model, messages)
            return _parse_extraction_result(content, required_fields)

        return await traced_call(
            tool_name="ExtractInformationTool",
            provider=_PROVIDER,
            operation="extract_information",
            request_summary=f"message_length={len(message)} fields={len(required_fields)}",
            call=_call,
            response_summary=lambda result: f"missing={len(result.missing_fields)}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def generate_response(self, context: ResponseContext) -> str:
        prompt = (
            "Sos el asistente de WhatsApp de una clínica dental en Argentina. Escribí una "
            "respuesta breve, cálida y profesional en español para el paciente, según esta "
            f"intención: {context.intent} y estos datos ya conocidos: {context.collected_data}."
        )
        messages = [{"role": "system", "content": prompt}]

        async def _call() -> str:
            return await self._client.chat_completion(self._model, messages, temperature=0.3)

        return await traced_call(
            tool_name="GenerateResponseTool",
            provider=_PROVIDER,
            operation="generate_response",
            request_summary=f"intent={context.intent}",
            call=_call,
            response_summary=lambda text: f"response_length={len(text)}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )


def _parse_intent_result(content: str) -> IntentResult:
    try:
        data = json.loads(content)
        intent = str(data["intent"])
        confidence = float(data["confidence"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise LLMInvalidResponseError(
            f"Model output was not the expected intent JSON shape: {content!r}"
        ) from exc
    if intent not in _INTENT_LABELS:
        raise LLMInvalidResponseError(f"Model returned an unrecognized intent label: {intent!r}")
    return IntentResult(intent=intent, confidence=confidence)


def _parse_extraction_result(content: str, required_fields: list[str]) -> ExtractionResult:
    try:
        data = json.loads(content)
        fields = dict(data["fields"])
        missing_fields = [str(f) for f in data["missing_fields"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise LLMInvalidResponseError(
            f"Model output was not the expected extraction JSON shape: {content!r}"
        ) from exc
    # Fail-closed: any required field the model didn't explicitly account
    # for (in either fields or missing_fields) is treated as missing
    # rather than silently assumed present.
    accounted_for = set(fields) | set(missing_fields)
    for field in required_fields:
        if field not in accounted_for:
            missing_fields.append(field)
    return ExtractionResult(fields=fields, missing_fields=missing_fields)


__all__ = ["LLMProviderError", "OpenAICompatibleLLMProvider"]
