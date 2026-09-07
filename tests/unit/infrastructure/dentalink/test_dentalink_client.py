import httpx
import pytest

import app.infrastructure.dentalink.client as client_module
from app.infrastructure.dentalink.client import DentalinkClient
from app.infrastructure.dentalink.exceptions import (
    DentalinkAPIError,
    DentalinkAuthError,
    DentalinkInvalidResponseError,
)


async def _no_sleep(_seconds: float) -> None:
    return None


def _capture_requests(monkeypatch: pytest.MonkeyPatch, response: httpx.Response):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    return captured


@pytest.mark.asyncio
async def test_get_sends_authorization_header_and_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, httpx.Response(200, json={"data": [{"id": 1}]}))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    result = await client.get("/v1/dentistas")

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.dentalink.healthatom.com/api/v1/dentistas"
    assert request.headers["authorization"] == "Token secret-token"
    assert request.method == "GET"
    assert result == {"data": [{"id": 1}]}


@pytest.mark.asyncio
async def test_get_strips_trailing_slash_from_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_requests(monkeypatch, httpx.Response(200, json={}))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api/",
        access_token="secret-token",
        timeout_seconds=15,
    )

    await client.get("/v1/dentistas")

    assert captured[0].url == "https://api.dentalink.healthatom.com/api/v1/dentistas"


@pytest.mark.asyncio
async def test_get_passes_query_params_through(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_requests(monkeypatch, httpx.Response(200, json={}))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    await client.get("/v5/agendas", params={"filtro[id_sucursal][eq]": "1"})

    assert captured[0].url.params["filtro[id_sucursal][eq]"] == "1"


@pytest.mark.asyncio
async def test_post_sends_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import json as json_module

    captured = _capture_requests(monkeypatch, httpx.Response(201, json={"id": 42}))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    result = await client.post("/v1/citas/", json={"id_paciente": "1"})

    assert json_module.loads(captured[0].content) == {"id_paciente": "1"}
    assert captured[0].method == "POST"
    assert result == {"id": 42}


@pytest.mark.asyncio
async def test_put_sends_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import json as json_module

    captured = _capture_requests(monkeypatch, httpx.Response(200, json={"id": 42}))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    await client.put("/v1/citas/42", json={"id_estado": 7})

    assert captured[0].method == "PUT"
    assert json_module.loads(captured[0].content) == {"id_estado": 7}


@pytest.mark.asyncio
async def test_raises_auth_error_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(401, text="unauthorized"))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="bad-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkAuthError):
        await client.get("/v1/dentistas")


@pytest.mark.asyncio
async def test_raises_auth_error_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(403, text="forbidden"))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="bad-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkAuthError):
        await client.get("/v1/dentistas")


@pytest.mark.asyncio
async def test_raises_api_error_on_other_non_2xx_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(409, text="conflict"))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkAPIError) as exc_info:
        await client.get("/v1/citas/")

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_raises_invalid_response_error_on_non_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, httpx.Response(200, text="<html>not json</html>"))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkInvalidResponseError):
        await client.get("/v1/dentistas")


@pytest.mark.asyncio
async def test_raises_timeout_error_when_request_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    from app.infrastructure.dentalink.exceptions import DentalinkTimeoutError

    with pytest.raises(DentalinkTimeoutError):
        await client.get("/v1/dentistas")


@pytest.mark.asyncio
async def test_get_retries_transient_timeouts_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    result = await client.get("/v1/pacientes")

    assert attempts == 3
    assert result == {"data": []}


@pytest.mark.asyncio
async def test_get_gives_up_after_max_attempts_on_persistent_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    from app.infrastructure.dentalink.exceptions import DentalinkTimeoutError

    with pytest.raises(DentalinkTimeoutError):
        await client.get("/v1/pacientes")

    assert attempts == 3  # bounded retry, not unbounded


@pytest.mark.asyncio
async def test_get_retries_a_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                429, json={"error": {"code": 429, "message": "Too Many Attempts."}}
            )
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    monkeypatch.setattr(client_module.asyncio, "sleep", _no_sleep)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    result = await client.get("/v5/agendas")

    assert attempts == 3
    assert result == {"data": []}


@pytest.mark.asyncio
async def test_get_gives_up_after_max_attempts_on_persistent_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"error": {"code": 429, "message": "Too Many Attempts."}})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    monkeypatch.setattr(client_module.asyncio, "sleep", _no_sleep)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkAPIError) as exc_info:
        await client.get("/v5/agendas")

    assert attempts == 3  # bounded retry, not unbounded
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_get_honours_retry_after_header_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"error": {"code": 429, "message": "Too Many Attempts."}},
            )
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    slept_for: list[float] = []

    async def _capture_sleep(seconds: float) -> None:
        slept_for.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", _capture_sleep)
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="secret-token",
        timeout_seconds=15,
    )

    result = await client.get("/v5/agendas")

    assert result == {"data": []}
    assert slept_for == [2.0]


@pytest.mark.asyncio
async def test_api_error_never_includes_the_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, httpx.Response(500, text="internal error"))
    client = DentalinkClient(
        base_url="https://api.dentalink.healthatom.com/api",
        access_token="super-secret-token",
        timeout_seconds=15,
    )

    with pytest.raises(DentalinkAPIError) as exc_info:
        await client.get("/v1/pacientes")

    assert "super-secret-token" not in str(exc_info.value)
