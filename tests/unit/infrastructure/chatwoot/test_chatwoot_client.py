import httpx
import pytest

import app.infrastructure.chatwoot.client as client_module
from app.infrastructure.chatwoot.client import ChatwootClient
from app.infrastructure.chatwoot.exceptions import ChatwootAPIError

_BASE_URL = "https://chatwoot.example.com"
_ACCOUNT_ID = "1"
_API_ACCESS_TOKEN = "cw-api-access-token"
_AGENT_BOT_TOKEN = "cw-agent-bot-token"
_INBOX_ID = "7"


def _capture_requests(monkeypatch: pytest.MonkeyPatch, json_response: dict | None = None):
    """Redirects the client's internal `httpx.AsyncClient` through a
    `MockTransport` so tests assert on the real outgoing request shape
    without any network call — same pattern as
    `tests/unit/infrastructure/ycloud/test_ycloud_client.py`.
    """
    captured: list[httpx.Request] = []
    response_body = json_response if json_response is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=response_body)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    return captured


def _make_client() -> ChatwootClient:
    return ChatwootClient(
        base_url=_BASE_URL,
        account_id=_ACCOUNT_ID,
        api_access_token=_API_ACCESS_TOKEN,
        agent_bot_token=_AGENT_BOT_TOKEN,
        inbox_id=_INBOX_ID,
    )


@pytest.mark.asyncio
async def test_get_conversation_labels_sends_a_get_with_the_api_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(
        monkeypatch, json_response={"payload": ["vip", "administracion"]}
    )
    client = _make_client()

    labels = await client.get_conversation_labels("chatwoot-conv-1")

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url == (
        f"{_BASE_URL}/api/v1/accounts/{_ACCOUNT_ID}"
        "/conversations/chatwoot-conv-1/labels"
    )
    assert request.headers["api_access_token"] == _API_ACCESS_TOKEN
    assert labels == ["vip", "administracion"]


@pytest.mark.asyncio
async def test_get_conversation_labels_returns_an_empty_list_when_the_payload_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, json_response={"payload": []})
    client = _make_client()

    labels = await client.get_conversation_labels("chatwoot-conv-1")

    assert labels == []


@pytest.mark.asyncio
async def test_get_conversation_labels_raises_chatwoot_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="conversation not found")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = _make_client()

    with pytest.raises(ChatwootAPIError) as exc_info:
        await client.get_conversation_labels("missing")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_conversation_labels_sends_a_post_with_the_api_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch)
    client = _make_client()

    await client.set_conversation_labels("chatwoot-conv-1", ["vip", "administracion"])

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url == (
        f"{_BASE_URL}/api/v1/accounts/{_ACCOUNT_ID}"
        "/conversations/chatwoot-conv-1/labels"
    )
    assert request.headers["api_access_token"] == _API_ACCESS_TOKEN
