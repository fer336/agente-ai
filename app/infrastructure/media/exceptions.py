class MediaDownloadError(Exception):
    """Raised by `MediaDownloader.download()` for any rejected/failed download
    (PRD.md §24.3, §74.7, §75.8).

    `reason` is a short machine-readable code —
    `"ssrf_blocked"` / `"redirect_blocked"` / `"size_exceeded"` /
    `"timeout"` / `"http_error"` — for callers (`TranscribeAudioUseCase`) to
    classify without string-matching the message.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)
