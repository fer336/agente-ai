import hashlib
import os
import tempfile

from app.domain.repositories.media_downloader import DownloadedMedia


class FakeMediaDownloader:
    """In-memory fake implementing `MediaDownloader` for local dev and tests.

    Writes `content` to a REAL temporary file (same contract as the real
    downloader: callers must be able to open/delete `DownloadedMedia.path`)
    so `TranscribeAudioUseCase`'s "always delete the temp file" behavior is
    exercised the same way against both the fake and the real adapter.
    """

    def __init__(
        self,
        content: bytes = b"",
        content_type: str | None = "audio/ogg",
        raises: Exception | None = None,
    ) -> None:
        self._content = content
        self._content_type = content_type
        self._raises = raises
        self.calls: list[str] = []

    async def download(self, url: str, *, max_size_bytes: int) -> DownloadedMedia:
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises

        fd, path = tempfile.mkstemp(prefix="fake-media-download-")
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(self._content)

        return DownloadedMedia(
            path=path,
            size_bytes=len(self._content),
            sha256=hashlib.sha256(self._content).hexdigest(),
            content_type=self._content_type,
        )
