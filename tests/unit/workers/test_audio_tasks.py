import pytest

from app.domain.entities.media_processing_job import MediaProcessingJob
from app.workers.audio_tasks import process_pending_audio_jobs
from tests.fixtures.gateways import make_media_processing_job_repository


class _RecordingTranscribeAudioUseCase:
    def __init__(self) -> None:
        self.executed_job_ids: list[str] = []

    async def execute(self, job_id: str) -> None:
        self.executed_job_ids.append(job_id)


def _job(job_id: str, status: str = "pending") -> MediaProcessingJob:
    return MediaProcessingJob(
        id=job_id,
        message_id=f"msg-{job_id}",
        status=status,
        media_id="media-1",
        media_mime_type="audio/ogg",
        attempts=0,
    )


@pytest.mark.asyncio
async def test_processes_every_pending_job():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job("job-1"))
    await job_repository.save(_job("job-2"))
    use_case = _RecordingTranscribeAudioUseCase()

    count = await process_pending_audio_jobs(job_repository, use_case)

    assert count == 2
    assert use_case.executed_job_ids == ["job-1", "job-2"]


@pytest.mark.asyncio
async def test_ignores_non_pending_jobs():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job("job-1", status="completed"))
    use_case = _RecordingTranscribeAudioUseCase()

    count = await process_pending_audio_jobs(job_repository, use_case)

    assert count == 0
    assert use_case.executed_job_ids == []


@pytest.mark.asyncio
async def test_respects_batch_size():
    job_repository = make_media_processing_job_repository()
    await job_repository.save(_job("job-1"))
    await job_repository.save(_job("job-2"))
    await job_repository.save(_job("job-3"))
    use_case = _RecordingTranscribeAudioUseCase()

    count = await process_pending_audio_jobs(job_repository, use_case, batch_size=2)

    assert count == 2
    assert use_case.executed_job_ids == ["job-1", "job-2"]


@pytest.mark.asyncio
async def test_returns_zero_when_no_jobs_pending():
    job_repository = make_media_processing_job_repository()
    use_case = _RecordingTranscribeAudioUseCase()

    count = await process_pending_audio_jobs(job_repository, use_case)

    assert count == 0
