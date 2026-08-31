import pytest

from app.domain.entities.media_processing_job import MediaProcessingJob
from app.infrastructure.database.fake_media_processing_job_repository import (
    FakeMediaProcessingJobRepository,
)


def _job(id_: str, message_id: str, status: str = "pending") -> MediaProcessingJob:
    return MediaProcessingJob(
        id=id_,
        message_id=message_id,
        status=status,
        media_id="media-1",
        media_mime_type="audio/ogg",
        attempts=0,
    )


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1"))

    fetched = await repository.get_by_id("job-1")

    assert fetched is not None
    assert fetched.status == "pending"


@pytest.mark.asyncio
async def test_get_by_message_id_finds_the_job():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1"))

    fetched = await repository.get_by_message_id("msg-1")

    assert fetched is not None
    assert fetched.id == "job-1"


@pytest.mark.asyncio
async def test_transition_status_succeeds_when_status_matches():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1"))

    won = await repository.transition_status(
        "job-1", from_status="pending", to_status="downloading"
    )

    assert won is True
    fetched = await repository.get_by_id("job-1")
    assert fetched is not None
    assert fetched.status == "downloading"


@pytest.mark.asyncio
async def test_transition_status_fails_when_status_does_not_match():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1"))
    await repository.transition_status("job-1", from_status="pending", to_status="downloading")

    won = await repository.transition_status(
        "job-1", from_status="pending", to_status="downloading"
    )

    assert won is False


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending_jobs_oldest_first():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1", status="completed"))
    await repository.save(_job("job-2", "msg-2", status="pending"))
    await repository.save(_job("job-3", "msg-3", status="pending"))

    pending = await repository.list_pending(limit=10)

    assert [job.id for job in pending] == ["job-2", "job-3"]


@pytest.mark.asyncio
async def test_list_pending_respects_limit():
    repository = FakeMediaProcessingJobRepository()
    await repository.save(_job("job-1", "msg-1", status="pending"))
    await repository.save(_job("job-2", "msg-2", status="pending"))

    pending = await repository.list_pending(limit=1)

    assert len(pending) == 1
