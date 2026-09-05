import json as json_module

import httpx
import pytest

import app.infrastructure.llm.client as client_module
from app.infrastructure.llm.client import OpenAICompatibleLLMClient
from app.infrastructure.llm.exceptions import (
    LLMAPIError,
    LLMAuthError,
    LLMInvalidResponseError,
    LLMTimeoutError,
)


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


def _chat_response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_chat_completion_sends_bearer_auth_and_returns_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, _chat_response("hello back"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1",
        api_key="sk-secret",
        timeout_seconds=20,
    )

    result = await client.chat_completion(
        "gemini/gemini-3.7-flash", [{"role": "user", "content": "hi"}]
    )

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "http://100.109.17.87:20128/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-secret"
    body = json_module.loads(request.content)
    assert body["model"] == "gemini/gemini-3.7-flash"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert result == "hello back"


@pytest.mark.asyncio
async def test_chat_completion_always_disables_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    # 9Router streams Server-Sent Events by default, even without the
    # client asking for it (the opposite of OpenAI's own default) — a
    # missing `stream: false` here silently breaks every real call.
    captured = _capture_requests(monkeypatch, _chat_response("ok"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    body = json_module.loads(captured[0].content)
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_chat_completion_strips_trailing_slash_from_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, _chat_response("ok"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1/", api_key="sk-secret", timeout_seconds=20
    )

    await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    assert captured[0].url == "http://100.109.17.87:20128/v1/chat/completions"


@pytest.mark.asyncio
async def test_raises_auth_error_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(401, text="unauthorized"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="bad-key", timeout_seconds=20
    )

    with pytest.raises(LLMAuthError):
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_raises_api_error_on_other_non_2xx_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(500, text="internal error"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    with pytest.raises(LLMAPIError) as exc_info:
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_raises_invalid_response_error_on_non_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, httpx.Response(200, text="<html>not json</html>"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    with pytest.raises(LLMInvalidResponseError):
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_raises_invalid_response_error_on_unexpected_json_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, httpx.Response(200, json={"unexpected": "shape"}))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    with pytest.raises(LLMInvalidResponseError):
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_raises_invalid_response_error_when_content_is_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A gateway/model can accept the request and still return
    # `"content": null` (empty completion, refusal, tool-call-only
    # response) — `str(None)` must never be treated as a valid reply, or
    # the literal text "None" gets sent to the patient.
    _capture_requests(
        monkeypatch,
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": None}}]},
        ),
    )
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    with pytest.raises(LLMInvalidResponseError):
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_retries_transient_timeouts_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    result = await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    assert attempts == 3
    assert result == "ok"


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_on_persistent_timeout(
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
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1", api_key="sk-secret", timeout_seconds=20
    )

    with pytest.raises(LLMTimeoutError):
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    assert attempts == 3


@pytest.mark.asyncio
async def test_api_error_never_includes_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(500, text="internal error"))
    client = OpenAICompatibleLLMClient(
        base_url="http://100.109.17.87:20128/v1",
        api_key="super-secret-key",
        timeout_seconds=20,
    )

    with pytest.raises(LLMAPIError) as exc_info:
        await client.chat_completion("model", [{"role": "user", "content": "hi"}])

    assert "super-secret-key" not in str(exc_info.value)
