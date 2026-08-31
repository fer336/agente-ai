import httpx
import pytest

import app.infrastructure.telegram.telegram_alert_notifier as notifier_module
from app.infrastructure.telegram.telegram_alert_notifier import TelegramAlertNotifier


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

    monkeypatch.setattr(notifier_module.httpx, "AsyncClient", patched_async_client)
    return captured


@pytest.mark.asyncio
async def test_sends_chat_id_and_text_to_the_send_message_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, httpx.Response(200, json={"ok": True}))
    notifier = TelegramAlertNotifier(
        base_url="https://api.telegram.org", bot_token="secret-token", chat_id="chat-1",
        timeout_seconds=10,
    )

    await notifier.notify("🚨 something broke")

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.telegram.org/botsecret-token/sendMessage"
    assert b"chat-1" in request.content
    assert b"something" in request.content


@pytest.mark.asyncio
async def test_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(401, text="unauthorized"))
    notifier = TelegramAlertNotifier(
        base_url="https://api.telegram.org", bot_token="bad-token", chat_id="chat-1",
        timeout_seconds=10,
    )

    with pytest.raises(RuntimeError):
        await notifier.notify("hi")


@pytest.mark.asyncio
async def test_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(notifier_module.httpx, "AsyncClient", patched_async_client)
    notifier = TelegramAlertNotifier(
        base_url="https://api.telegram.org", bot_token="token", chat_id="chat-1",
        timeout_seconds=10,
    )

    with pytest.raises(RuntimeError):
        await notifier.notify("hi")
