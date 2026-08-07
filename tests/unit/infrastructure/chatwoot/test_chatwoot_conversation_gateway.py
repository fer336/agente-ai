import json

import httpx
import pytest

import app.infrastructure.chatwoot.chatwoot_conversation_gateway as gateway_module
from app.infrastructure.chatwoot.chatwoot_conversation_gateway import (
    ChatwootConversationGateway,
)


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Redirects the gateway's internal `httpx.AsyncClient` through a
    `MockTransport` so tests assert on the real outgoing request shape
    without any network call or extra test dependency (`httpx.MockTransport`
    ships with `httpx` itself, already a project dependency).
    """
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": 1})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", patched_async_client)
    return captured


@pytest.mark.asyncio
async def test_mirror_message_posts_to_chatwoot_messages_endpoint_with_agent_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DISCLOSED DEVIATION (Phase 5, task 5.4): this test was written AFTER
    # `ChatwootConversationGateway`'s production code, not before — no
    # separate RED cycle was run for this file specifically. It was
    # collapsed into the single 5.1 RED / 5.2-5.4 GREEN group per the
    # tasks doc's own grouping (mirrors the accepted PR2 2.5/2.7/2.8 and
    # PR4 4.12/4.13 disclosed-collapse pattern). This test IS a real,
    # non-tautological assertion of production behavior (captures the
    # actual outgoing `httpx.Request` via a `MockTransport`, no network
    # call), added because no live Chatwoot instance exists this etapa to
    # exercise the real adapter against — see the design doc's Open
    # Questions and this PR's Testing Strategy harness note.
    captured = _capture_requests(monkeypatch)
    gateway = ChatwootConversationGateway(
        base_url="https://chatwoot.example.com",
        account_id="7",
        api_token="agent-bot-token-abc",
    )

    await gateway.mirror_message("100", "Tu turno fue confirmado")

    assert len(captured) == 1
    request = captured[0]
    assert (
        request.url == "https://chatwoot.example.com/api/v1/accounts/7/conversations/100/messages"
    )
    assert request.headers["api_access_token"] == "agent-bot-token-abc"
    assert request.method == "POST"


@pytest.mark.asyncio
async def test_mirror_message_sends_the_exact_reply_text_and_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # TRIANGULATE: different conversation id, token, and text than the
    # test above, and a `base_url` with a trailing slash, proving the
    # URL/body are built from the real arguments (not hardcoded) and that
    # `base_url.rstrip("/")` actually runs.
    captured = _capture_requests(monkeypatch)
    gateway = ChatwootConversationGateway(
        base_url="https://chatwoot.example.com/",
        account_id="9",
        api_token="another-token",
    )

    await gateway.mirror_message("555", "Otra respuesta distinta")

    assert len(captured) == 1
    request = captured[0]
    assert (
        request.url == "https://chatwoot.example.com/api/v1/accounts/9/conversations/555/messages"
    )
    parsed_body = json.loads(request.content)
    assert parsed_body == {"content": "Otra respuesta distinta", "message_type": "outgoing"}
