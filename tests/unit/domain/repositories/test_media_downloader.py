from app.domain.repositories.media_downloader import DownloadedMedia, MediaDownloader


class ConformingMediaDownloader:
    async def download(self, url, *, max_size_bytes):
        return DownloadedMedia(path="/tmp/x", size_bytes=0, sha256="", content_type=None)


class PartialMediaDownloader:
    pass


def test_conforming_class_satisfies_media_downloader_protocol():
    assert isinstance(ConformingMediaDownloader(), MediaDownloader)


def test_partial_class_does_not_satisfy_media_downloader_protocol():
    assert not isinstance(PartialMediaDownloader(), MediaDownloader)
