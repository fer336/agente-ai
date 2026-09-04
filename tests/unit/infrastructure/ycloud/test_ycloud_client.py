import json

import httpx
import pytest

import app.infrastructure.ycloud.client as client_module
from app.domain.value_objects.interactive_button import InteractiveButton
from app.infrastructure.ycloud.client import YCloudClient
from app.infrastructure.ycloud.exceptions import YCloudAPIError


def _capture_requests(monkeypatch: pytest.MonkeyPatch, json_response: dict | None = None):
    """Redirects the client's internal `httpx.AsyncClient` through a
    `MockTransport` so tests assert on the real outgoing request shape
    without any network call.
    """
    captured: list[httpx.Request] = []
    response_body = json_response if json_response is not None else {"id": "wamid.fake-1"}

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


@pytest.mark.asyncio
async def test_send_text_posts_to_messages_endpoint_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch)
    client = YCloudClient(
        base_url="https://api.ycloud.com",
        api_key="yc-key-abc",
        whatsapp_number="+5491100000001",
    )

    external_id = await client.send_text("+5491122334455", "Tu turno fue confirmado")

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.ycloud.com/v2/whatsapp/messages"
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert request.method == "POST"
    body = json.loads(request.content)
    assert body == {
        "from": "+5491100000001",
        "to": "+5491122334455",
        "type": "text",
        "text": {"body": "Tu turno fue confirmado"},
    }
    assert external_id == "wamid.fake-1"


@pytest.mark.asyncio
async def test_send_text_strips_trailing_slash_from_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch)
    client = YCloudClient(
        base_url="https://api.ycloud.com/",
        api_key="yc-key-abc",
        whatsapp_number="+5491100000001",
    )

    await client.send_text("+5491122334455", "Hola")

    assert captured[0].url == "https://api.ycloud.com/v2/whatsapp/messages"


@pytest.mark.asyncio
async def test_send_buttons_posts_interactive_button_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch)
    client = YCloudClient(
        base_url="https://api.ycloud.com",
        api_key="yc-key-abc",
        whatsapp_number="+5491100000001",
    )
    buttons = [
        InteractiveButton(id="confirm", title="Confirmar"),
        InteractiveButton(id="cancel", title="Cancelar"),
    ]

    await client.send_buttons("+5491122334455", "¿Confirmás el turno?", buttons)

    body = json.loads(captured[0].content)
    assert body == {
        "from": "+5491100000001",
        "to": "+5491122334455",
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "¿Confirmás el turno?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "confirm", "title": "Confirmar"}},
                    {"type": "reply", "reply": {"id": "cancel", "title": "Cancelar"}},
                ]
            },
        },
    }


@pytest.mark.asyncio
async def test_send_text_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="bad-key", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError) as exc_info:
        await client.send_text("+5491122334455", "Hola")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_media_sends_api_key_and_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(
        monkeypatch,
        json_response={"url": "https://cdn.ycloud.com/media/1", "mime_type": "audio/ogg"},
    )
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    result = await client.get_media("media-1")

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.ycloud.com/v1/media/media-1"
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert request.method == "GET"
    assert result == {"url": "https://cdn.ycloud.com/media/1", "mime_type": "audio/ogg"}


@pytest.mark.asyncio
async def test_get_contact_sends_api_key_and_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(
        monkeypatch,
        json_response={"id": "contact-1", "phoneNumber": "+5491122334455"},
    )
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    result = await client.get_contact("contact-1")

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.ycloud.com/v2/contact/contacts/contact-1"
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert request.method == "GET"
    assert result == {"id": "contact-1", "phoneNumber": "+5491122334455"}


@pytest.mark.asyncio
async def test_get_contact_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError) as exc_info:
        await client.get_contact("missing")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_find_contact_by_phone_sends_the_filter_query_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(
        monkeypatch,
        json_response={"items": [{"id": "contact-1", "tags": ["vip"]}]},
    )
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    result = await client.find_contact_by_phone("+5491122334455")

    assert len(captured) == 1
    request = captured[0]
    assert request.url.path == "/v2/contact/contacts"
    assert dict(request.url.params) == {"filter.phoneNumber": "+5491122334455", "limit": "1"}
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert result == {"id": "contact-1", "tags": ["vip"]}


@pytest.mark.asyncio
async def test_find_contact_by_phone_returns_none_when_no_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(monkeypatch, json_response={"items": []})
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    result = await client.find_contact_by_phone("+5491199999999")

    assert result is None


@pytest.mark.asyncio
async def test_find_contact_by_phone_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError):
        await client.find_contact_by_phone("+5491122334455")


@pytest.mark.asyncio
async def test_update_contact_tags_sends_a_patch_with_the_full_tag_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, json_response={"id": "contact-1"})
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    await client.update_contact_tags("contact-1", ["vip", "Human"])

    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.ycloud.com/v2/contact/contacts/contact-1"
    assert request.method == "PATCH"
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert json.loads(request.content) == {"tags": ["vip", "Human"]}


@pytest.mark.asyncio
async def test_update_contact_tags_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError) as exc_info:
        await client.update_contact_tags("missing", ["Human"])

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_media_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError) as exc_info:
        await client.get_media("missing")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_send_typing_indicator_posts_to_the_wamid_scoped_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_requests(monkeypatch, json_response={})
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    await client.send_typing_indicator("wamid.ABC123")

    assert len(captured) == 1
    request = captured[0]
    assert (
        request.url
        == "https://api.ycloud.com/v2/whatsapp/inboundMessages/wamid.ABC123/typingIndicator"
    )
    assert request.headers["x-api-key"] == "yc-key-abc"
    assert request.method == "POST"


@pytest.mark.asyncio
async def test_send_typing_indicator_raises_ycloud_api_error_on_non_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="unknown wamid")

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_module.httpx, "AsyncClient", patched_async_client)
    client = YCloudClient(
        base_url="https://api.ycloud.com", api_key="yc-key-abc", whatsapp_number="+5491100000001"
    )

    with pytest.raises(YCloudAPIError) as exc_info:
        await client.send_typing_indicator("wamid.stale")

    assert exc_info.value.status_code == 404
