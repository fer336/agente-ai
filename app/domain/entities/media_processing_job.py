from dataclasses import dataclass


@dataclass
class MediaProcessingJob:
    """Minimal media processing job shell, sized to type repository Protocol signatures."""

    id: str
    message_id: str
    status: str
    media_id: str
    media_mime_type: str
    attempts: int
