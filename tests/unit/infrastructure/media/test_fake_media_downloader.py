import os

import pytest

from app.domain.repositories.media_downloader import MediaDownloader
from app.infrastructure.media.fake_media_downloader import FakeMediaDownloader


def test_fake_satisfies_media_downloader_protocol():
    assert isinstance(FakeMediaDownloader(), MediaDownloader)


@pytest.mark.asyncio
async def test_writes_content_to_a_real_temp_file():
    downloader = FakeMediaDownloader(content=b"fake-audio-bytes")

    result = await downloader.download("https://example.com/media/1", max_size_bytes=1_000)

    assert os.path.exists(result.path)
    with open(result.path, "rb") as f:
        assert f.read() == b"fake-audio-bytes"
    assert result.size_bytes == len(b"fake-audio-bytes")


@pytest.mark.asyncio
async def test_records_calls():
    downloader = FakeMediaDownloader(content=b"x")

    await downloader.download("https://example.com/media/1", max_size_bytes=1_000)

    assert downloader.calls == ["https://example.com/media/1"]


@pytest.mark.asyncio
async def test_raises_configured_exception():
    downloader = FakeMediaDownloader(raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await downloader.download("https://example.com/media/1", max_size_bytes=1_000)
