import asyncio

import httpx

from app.infrastructure.llm.exceptions import (
    LLMAPIError,
    LLMAuthError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)

#: Same bounded-retry rationale as `DentalinkClient`: only a transient
#: network timeout is retried, never a 4xx/5xx application response — a
#: chat-completion is not idempotent-safe to blindly retry after the
#: gateway has already accepted and started billing/processing it.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.05


class OpenAICompatibleLLMClient:
    """`httpx`-based client for an OpenAI-compatible `/chat/completions` gateway.

    Targets a 9Router instance (self-hosted, routes to 40+ backend
    providers behind one OpenAI-compatible API) — `base_url` and
    `api_key` are 9Router's, not a specific upstream provider's. Any
    other OpenAI-compatible gateway works identically; nothing here is
    9Router-specific beyond the name.
    """

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    async def chat_completion(
        self, model: str, messages: list[dict[str, str]], *, temperature: float = 0.0
    ) -> str:
        """Sends a chat-completion request, returns the first choice's raw
        message content (never parsed here — callers own their own
        expected shape, JSON or plain text).
        """
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            # 9Router streams Server-Sent Events by default even without a
            # client asking for it — the opposite of OpenAI's own default.
            # Explicit `stream: false` is required to get back the single
            # JSON object `chat_completion`'s own parsing below expects.
            "stream": False,
        }
        response: httpx.Response | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)
                break
            except httpx.TimeoutException as exc:
                if attempt == _MAX_ATTEMPTS:
                    # Never include the request body or the API key itself
                    # here — only the model name, which is not a secret.
                    raise LLMTimeoutError(
                        f"LLM request for model '{model}' timed out after {attempt} attempts"
                    ) from exc
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        assert response is not None  # loop always breaks or raises above

        if response.status_code in (401, 403):
            raise LLMAuthError(f"LLM gateway rejected credentials ({response.status_code})")
        if response.is_error:
            raise LLMAPIError(response.status_code, response.text)

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                # A gateway/model can accept the request and still return
                # `"content": null` (empty completion, refusal, tool-call-
                # only response) — `str(None)` must never be treated as a
                # valid reply, or the literal text "None" reaches the
                # patient.
                raise LLMInvalidResponseError(
                    f"LLM gateway returned non-string message content: {content!r}"
                )
            return content
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMInvalidResponseError(
                "LLM gateway response was not valid OpenAI-shaped chat-completion JSON"
            ) from exc
