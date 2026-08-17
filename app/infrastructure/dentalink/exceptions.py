class DentalinkError(Exception):
    """Base class for all Dentalink adapter errors (PRD.md §43.2 integration errors)."""


class DentalinkTimeoutError(DentalinkError):
    """The request to Dentalink timed out (`dentalink_timeout`)."""


class DentalinkAuthError(DentalinkError):
    """Dentalink rejected the request's credentials, 401/403 (`dentalink_auth_error`)."""


class DentalinkInvalidResponseError(DentalinkError):
    """Dentalink returned a body that isn't valid JSON (`dentalink_invalid_response`)."""


class DentalinkAPIError(DentalinkError):
    """Dentalink returned a non-2xx response not covered by a more specific error above."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Dentalink API returned {status_code}: {body}")
