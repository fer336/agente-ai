class FakeTranscriptionGateway:
    """In-memory fake implementing `TranscriptionGateway` for local dev and tests.

    `transcript` is returned verbatim for every call unless `raises` is set,
    in which case that exception is raised instead. `calls` records every
    `(audio_path, mime_type)` pair for test introspection.
    """

    def __init__(self, transcript: str = "", raises: Exception | None = None) -> None:
        self._transcript = transcript
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def transcribe(self, audio_path: str, mime_type: str) -> str:
        self.calls.append((audio_path, mime_type))
        if self._raises is not None:
            raise self._raises
        return self._transcript
