import pytest

from app.domain.repositories.media_gateway import MediaGateway, MediaLocation
from app.infrastructure.ycloud.fake_media_gateway import FakeYCloudMediaGateway


def test_satisfies_media_gateway_protocol():
    assert isinstance(FakeYCloudMediaGateway(), MediaGateway)


@pytest.mark.asyncio
async def test_returns_configured_location():
    location = MediaLocation(
        url="https://cdn.ycloud.com/media/1", mime_type="audio/ogg", sha256=None
    )
    gateway = FakeYCloudMediaGateway({"media-1": location})

    result = await gateway.get_media_location("media-1")

    assert result == location
    assert gateway.calls == ["media-1"]


@pytest.mark.asyncio
async def test_raises_when_media_id_not_configured():
    gateway = FakeYCloudMediaGateway()

    with pytest.raises(KeyError):
        await gateway.get_media_location("unknown")
