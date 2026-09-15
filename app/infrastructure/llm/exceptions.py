class LLMProviderError(Exception):
    """Base class for all LLM adapter errors (PRD.md §43.2/§43.4)."""


class LLMTimeoutError(LLMProviderError):
    """The request to the LLM gateway timed out (`openai_timeout`)."""


class LLMAuthError(LLMProviderError):
    """The LLM gateway rejected the request's credentials, 401/403."""


class LLMInvalidResponseError(LLMProviderError):
    """The LLM gateway returned a body that isn't valid JSON, or the
    model's own output wasn't the structured JSON the prompt asked for
    (`invalid_llm_output`).
    """


class LLMQuotaExceededError(LLMProviderError):
    """The LLM gateway returned 429 — the account/plan's quota or rate
    limit was hit (`llm_quota_exceeded`). Distinct from `LLMAPIError`:
    unlike a one-off 5xx blip, a quota exhaustion means every subsequent
    turn fails too until it resets or is topped up, so it is classified
    and alerted on immediately rather than only after repeating (see
    `app.application.errors.error_service`'s `_ALWAYS_CRITICAL`).
    """

    def __init__(self, body: str) -> None:
        self.status_code = 429
        self.body = body
        super().__init__(f"LLM gateway quota/rate limit exceeded (429): {body}")


class LLMAPIError(LLMProviderError):
    """The LLM gateway returned a non-2xx response not covered above."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"LLM gateway returned {status_code}: {body}")
