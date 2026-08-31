from app.domain.entities.media_processing_job import MediaProcessingJob


class FakeMediaProcessingJobRepository:
    """In-memory fake implementing `MediaProcessingJobRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._jobs_by_id: dict[str, MediaProcessingJob] = {}
        # Insertion order stands in for `created_at` ordering (`list_pending`
        # returns oldest first) — every fake in this codebase is exercised
        # synchronously in tests, so insertion order IS creation order.
        self._insertion_order: list[str] = []

    async def get_by_id(self, job_id: str) -> MediaProcessingJob | None:
        return self._jobs_by_id.get(job_id)

    async def get_by_message_id(self, message_id: str) -> MediaProcessingJob | None:
        for job in self._jobs_by_id.values():
            if job.message_id == message_id:
                return job
        return None

    async def save(self, job: MediaProcessingJob) -> None:
        if job.id not in self._jobs_by_id:
            self._insertion_order.append(job.id)
        self._jobs_by_id[job.id] = job

    async def list_pending(self, limit: int) -> list[MediaProcessingJob]:
        pending = [
            self._jobs_by_id[job_id]
            for job_id in self._insertion_order
            if self._jobs_by_id[job_id].status == "pending"
        ]
        return pending[:limit]

    async def transition_status(self, job_id: str, *, from_status: str, to_status: str) -> bool:
        job = self._jobs_by_id.get(job_id)
        if job is None or job.status != from_status:
            return False
        self._jobs_by_id[job_id] = MediaProcessingJob(
            id=job.id,
            message_id=job.message_id,
            status=to_status,
            media_id=job.media_id,
            media_mime_type=job.media_mime_type,
            attempts=job.attempts,
            last_error=job.last_error,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )
        return True
