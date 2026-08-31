from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DownloadedMedia:
    """Result of a completed, SSRF-safe media download.

    `path` points at a temporary file the caller owns and MUST delete once
    done with it (success or failure — PRD.md §74.7: "Los temporales se
    eliminarán también ante excepciones"). `sha256` is computed from the
    actual bytes received, for `TranscribeAudioUseCase` to compare against
    `MediaLocation.sha256` when the vendor reports one.
    """

    path: str
    size_bytes: int
    sha256: str
    content_type: str | None


@runtime_checkable
class MediaDownloader(Protocol):
    """Port to a safe media-download implementation (PRD.md §24.3, §74.7).

    A real implementation MUST enforce, before returning any bytes to a
    caller: host allowlisting, SSRF protection (no private/loopback/
    metadata-service addresses, no redirect to a disallowed host), and a
    hard cap on bytes received (`max_size_bytes`) enforced DURING the
    download, not only after it completes.
    """

    async def download(self, url: str, *, max_size_bytes: int) -> DownloadedMedia: ...
