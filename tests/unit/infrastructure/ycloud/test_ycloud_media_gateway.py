import pytest

from app.domain.repositories.media_gateway import MediaGateway
from app.infrastructure.ycloud.client import YCloudClient
from app.infrastructure.ycloud.media_gateway import YCloudMediaGateway


class _StubYCloudClient:
    def __init__(self, response: dict[str, object]) -> None:
        self._response = response
        self.calls: list[str] = []

    async def get_media(self, media_id: str) -> dict[str, object]:
        self.calls.append(media_id)
        return self._response


def test_satisfies_media_gateway_protocol():
    assert isinstance(YCloudMediaGateway(client=YCloudClient("https://x", "k", "+1")), MediaGateway)


@pytest.mark.asyncio
async def test_maps_client_response_to_media_location():
    client = _StubYCloudClient(
        {"url": "https://cdn.ycloud.com/media/1", "mime_type": "audio/ogg", "sha256": "abc123"}
    )
    gateway = YCloudMediaGateway(client=client)  # type: ignore[arg-type]

    location = await gateway.get_media_location("media-1")

    assert location.url == "https://cdn.ycloud.com/media/1"
    assert location.mime_type == "audio/ogg"
    assert location.sha256 == "abc123"
    assert client.calls == ["media-1"]


@pytest.mark.asyncio
async def test_maps_missing_sha256_to_none():
    client = _StubYCloudClient({"url": "https://cdn.ycloud.com/media/1", "mime_type": "audio/ogg"})
    gateway = YCloudMediaGateway(client=client)  # type: ignore[arg-type]

    location = await gateway.get_media_location("media-1")

    assert location.sha256 is None
