from typing import Protocol, runtime_checkable

from app.domain.entities.media_processing_job import MediaProcessingJob


@runtime_checkable
class MediaProcessingJobRepository(Protocol):
    """Port to durable storage for inbound-media (audio) processing jobs."""

    async def get_by_id(self, job_id: str) -> MediaProcessingJob | None: ...

    async def get_by_message_id(self, message_id: str) -> MediaProcessingJob | None: ...

    async def save(self, job: MediaProcessingJob) -> None: ...

    async def list_pending(self, limit: int) -> list[MediaProcessingJob]:
        """Returns up to `limit` jobs still in `pending` status, oldest first.

        The audio worker's claim loop (`app.workers.audio_tasks`) reads this
        list and then calls `transition_status` per job — the atomic,
        mutually-exclusive claim happens there, not here; a job returned by
        this call is only a CANDIDATE, since another worker may claim it
        first.
        """
        ...

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
