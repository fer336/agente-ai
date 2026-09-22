class ChatwootAPIError(Exception):
    """Raised when the Chatwoot REST API returns a non-2xx response.

    Mirrors `app.infrastructure.ycloud.exceptions.YCloudAPIError` — same
    optional `status_code`, same shape, so callers that map gateway
    exceptions to `tool_executions.http_status` (PRD.md §41) can reuse the
    same pattern.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)
