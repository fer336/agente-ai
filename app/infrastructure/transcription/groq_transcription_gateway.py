import httpx

from app.application.errors.error_types import (
    TRANSCRIPTION_AUTH_ERROR,
    TRANSCRIPTION_INVALID_RESPONSE,
    TRANSCRIPTION_TIMEOUT,
)
from app.infrastructure.observability.tool_tracing import traced_call
from app.infrastructure.transcription.exceptions import (
    TranscriptionAPIError,
    TranscriptionAuthError,
    TranscriptionTimeoutError,
)

_PROVIDER = "groq"


def _http_status_of(exc: Exception) -> str | None:
    if isinstance(exc, TranscriptionAPIError):
        return str(exc.status_code)
    if isinstance(exc, TranscriptionTimeoutError):
        return "timeout"
    if isinstance(exc, TranscriptionAuthError):
        return "auth_error"
    return None


def _error_type_of(exc: Exception) -> str:
    if isinstance(exc, TranscriptionTimeoutError):
        return TRANSCRIPTION_TIMEOUT
    if isinstance(exc, TranscriptionAuthError):
        return TRANSCRIPTION_AUTH_ERROR
    return TRANSCRIPTION_INVALID_RESPONSE


class GroqTranscriptionGateway:
    """`httpx`-based `TranscriptionGateway` adapter for Groq's OpenAI-compatible
    `/audio/transcriptions` endpoint (PRD.md §5.2's "Proveedor de
    transcripción abstraído mediante interfaces").

    UNVERIFIED against a live Groq account (no live credentials in this
    environment — see this change's report). Endpoint shape follows Groq's
    publicly documented OpenAI-compatible Audio API
    (`POST {base_url}/audio/transcriptions`, multipart `file`+`model` fields,
    `Authorization: Bearer {api_key}`, JSON response `{"text": "..."}`).
    Confirm against real Groq API docs/credentials before production use.
    Wired into DI (see `app.api.dependencies.gateways.get_transcription_gateway`)
    whenever `settings.groq_api_key` is configured, else falls back to
    `FakeTranscriptionGateway`, matching every other gateway's
    fake-by-default swap-point convention in this codebase.
    """

    def __init__(
        self, base_url: str, api_key: str, model: str, timeout_seconds: float
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def transcribe(self, audio_path: str, mime_type: str) -> str:
        async def _call() -> str:
            url = f"{self._base_url}/audio/transcriptions"
            headers = {"Authorization": f"Bearer {self._api_key}"}
            try:
                with open(audio_path, "rb") as audio_file:
                    async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                        response = await client.post(
                            url,
                            headers=headers,
                            data={"model": self._model},
                            files={"file": ("audio", audio_file, mime_type)},
                        )
            except httpx.TimeoutException as exc:
                raise TranscriptionTimeoutError(
                    f"Groq transcription request timed out after {self._timeout_seconds}s"
                ) from exc

            if response.status_code in (401, 403):
                raise TranscriptionAuthError(
                    f"Groq rejected credentials ({response.status_code})"
                )
            if response.is_error:
                raise TranscriptionAPIError(response.status_code, response.text)

            data = response.json()
            return str(data.get("text", ""))

        return await traced_call(
            tool_name="TranscribeAudioTool",
            provider=_PROVIDER,
            operation="transcribe",
            request_summary=f"mime_type={mime_type} model={self._model}",
            call=_call,
            response_summary=lambda text: f"{len(text)} chars",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )
