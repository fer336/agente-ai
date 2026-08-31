from dataclasses import dataclass
from datetime import datetime

#: PRD.md §33's documented `media_processing_jobs.status` enum.
PENDING = "pending"
DOWNLOADING = "downloading"
TRANSCRIBING = "transcribing"
COMPLETED = "completed"
FAILED = "failed"
REJECTED = "rejected"


@dataclass
class MediaProcessingJob:
    """Minimal media processing job shell, sized to type repository Protocol signatures."""

    id: str
    message_id: str
    status: str
    media_id: str
    media_mime_type: str
    attempts: int
    last_error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
