from typing import Protocol, runtime_checkable

from app.domain.entities.media_processing_job import MediaProcessingJob


@runtime_checkable
class MediaProcessingJobRepository(Protocol):
    """Port to durable storage for inbound-media (audio) processing jobs."""

    async def get_by_id(self, job_id: str) -> MediaProcessingJob | None: ...

    async def get_by_message_id(self, message_id: str) -> MediaProcessingJob | None: ...

    async def save(self, job: MediaProcessingJob) -> None: ...

    async def transition_status(
        self, job_id: str, *, from_status: str, to_status: str
    ) -> bool:
        """Atomically moves status from `from_status` to `to_status`.

        Returns True if this call performed the transition, False if the
        row was no longer in `from_status` — same mutual-exclusion guard as
        `ScheduledActionRepository.transition_status` (PRD.md §75.8:
        "Webhook duplicado -> no repite transcripción").
        """
        ...
