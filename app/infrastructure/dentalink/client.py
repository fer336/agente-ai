import asyncio

import httpx

from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkAuthError,
    DentalinkInvalidResponseError,
    DentalinkTimeoutError,
)

#: Bounded retry. Two transient conditions are retried here:
#: `httpx.TimeoutException` (no response was ever received) and HTTP 429
#: (a response WAS received, but Dentalink is rate-limiting us — confirmed
#: in production: a 30-day `/v5/agendas` search that never accumulates
#: enough slots to stop early fires one request per day and Dentalink
#: answers "429 Too Many Attempts" partway through). Never any other 4xx/5xx
#: — those are only ever seen *after* a response was successfully received,
#: and retrying e.g. a 409 could double-create a patient/appointment on a
#: write that actually succeeded server-side.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.05
#: Fallback backoff for a 429 that carries no `Retry-After` header. Kept
#: separate from `_RETRY_BACKOFF_SECONDS` because a rate limit is Dentalink
#: deliberately asking for more spacing, not a fluke worth retrying fast.
_RATE_LIMIT_BACKOFF_SECONDS = 0.5


def _rate_limit_backoff_seconds(response: httpx.Response, attempt: int) -> float:
    """Honours Dentalink's own `Retry-After` (seconds) when present; falls
    back to a fixed per-attempt backoff otherwise."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return _RATE_LIMIT_BACKOFF_SECONDS * attempt


class DentalinkClient:
    """`httpx`-based client for the Dentalink REST API (PRD.md §27.1).

    Base URL, auth scheme (`Authorization: Token {access_token}`), and every
    endpoint path used by the gateways above this client come directly from
    PRD.md §27.1's verified endpoint table — no invented routes. This class
    only moves raw JSON in and out; PRD.md §27.6's documented
    inconsistencies (dentista/profesional naming, id_profesional vs
    id_dentista, mostrar_detalles vs mostar_detalles) are isolated to the
    mapper functions in `appointment_gateway.py`/`agreement_gateway.py`,
    never leaked past this boundary.

    UNVERIFIED against a live Dentalink account (no live credentials in this
    environment — see this change's report). Response shapes below follow
    the PRD's documented examples; confirm against real Dentalink responses
    before production use.
    """

    def __init__(self, base_url: str, access_token: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds

    async def get(self, path: str, params: dict[str, str] | None = None) -> object:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: dict[str, object]) -> object:
        return await self._request("POST", path, json=json)

    async def put(self, path: str, json: dict[str, object]) -> object:
        return await self._request("PUT", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> object:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Token {self._access_token}"}
        response: httpx.Response | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.request(
                        method, url, headers=headers, params=params, json=json
                    )
            except httpx.TimeoutException as exc:
                if attempt == _MAX_ATTEMPTS:
                    # Never include request/response bodies or the token
                    # itself here — only the path, which is not a secret.
                    raise DentalinkTimeoutError(
                        f"Dentalink request to {path} timed out after {attempt} attempts"
                    ) from exc
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue
            if response.status_code == 429 and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_rate_limit_backoff_seconds(response, attempt))
                continue
            break
        assert response is not None  # loop always breaks or raises above

        if response.status_code in (401, 403):
            raise DentalinkAuthError(
                f"Dentalink rejected credentials for {path} ({response.status_code})"
            )
        if response.is_error:
            raise DentalinkAPIError(response.status_code, response.text)

        try:
            return response.json()
        except ValueError as exc:
            raise DentalinkInvalidResponseError(
                f"Dentalink response for {path} was not valid JSON"
            ) from exc


