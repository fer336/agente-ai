from typing import Protocol, runtime_checkable


@runtime_checkable
class TranscriptionGateway(Protocol):
    """Port to an abstracted audio-transcription provider (PRD.md §5.2, §28.4).

    `audio_path` is a path to an already-downloaded, already-validated local
    file — this Protocol has no concept of the original media URL, MIME
    allowlist, or size/duration limits, all of which are enforced upstream
    by `TranscribeAudioUseCase` before this is ever called. The returned
    string is the raw transcript text — PRD.md §74.7 requires callers to
    treat it as untrusted input, never as something this Protocol itself
    sanitizes.
    """

    async def transcribe(self, audio_path: str, mime_type: str) -> str: ...
