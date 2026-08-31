class TranscriptionError(Exception):
    """Base class for all transcription-provider adapter errors (PRD.md §66)."""


class TranscriptionTimeoutError(TranscriptionError):
    """The request to the transcription provider timed out."""


class TranscriptionAuthError(TranscriptionError):
    """The transcription provider rejected the request's credentials, 401/403."""


class TranscriptionAPIError(TranscriptionError):
    """The transcription provider returned a non-2xx response not covered above."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Transcription provider returned {status_code}: {body}")
