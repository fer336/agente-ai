import json

import httpx
import pytest

import app.infrastructure.ycloud.handoff_gateway as handoff_gateway_module
from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.ycloud.exceptions import YCloudAPIError
from app.infrastructure.ycloud.handoff_gateway import YCloudHandoffGateway


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(handoff_gateway_module.httpx, "AsyncClient", patched_async_client)
    return captured


@pytest.mark.asyncio
async def test_request_handoff_puts_labels_for_the_phone_derived_from_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch)
    gateway = YCloudHandoffGateway(base_url="https://api.ycloud.com", api_key="yc-key")

    await gateway.request_handoff(
        ConversationId("ycloud-+5491122334455"), "patient requested a human"
    )

    assert len(captured) == 1
    request = captured[0]
    assert (
        request.url
        == "https://api.ycloud.com/v2/whatsapp/conversations/+5491122334455/labels"
    )
    assert request.headers["x-api-key"] == "yc-key"
    assert request.method == "PUT"
    body = json.loads(request.content)
    assert body == {"labels": ["handoff"], "note": "patient requested a human"}


@pytest.mark.asyncio
async def test_request_handoff_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(handoff_gateway_module.httpx, "AsyncClient", patched_async_client)
    gateway = YCloudHandoffGateway(base_url="https://api.ycloud.com", api_key="yc-key")

    with pytest.raises(YCloudAPIError):
        await gateway.request_handoff(ConversationId("ycloud-+5491122334455"), "reason")


def test_ycloud_handoff_gateway_satisfies_human_handoff_gateway_protocol():
    assert isinstance(
        YCloudHandoffGateway(base_url="https://api.ycloud.com", api_key="yc-key"),
        HumanHandoffGateway,
    )
