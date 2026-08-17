from app.domain.entities.media_processing_job import MediaProcessingJob
from app.infrastructure.database.repositories.media_processing_job_repository import (
    SqlAlchemyMediaProcessingJobRepository,
)


def _job(message_id: str, job_id: str, status: str) -> MediaProcessingJob:
    return MediaProcessingJob(
        id=job_id,
        message_id=message_id,
        status=status,
        media_id="media-1",
        media_mime_type="audio/ogg",
        attempts=0,
    )


async def test_save_then_get_by_id_round_trips_a_media_processing_job(db_session, message_id):
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)
    job = _job(message_id, "job-1", "pending")

    await repository.save(job)
    fetched = await repository.get_by_id("job-1")

    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.media_mime_type == "audio/ogg"


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_get_by_message_id_returns_the_job_for_that_message(db_session, message_id):
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)
    await repository.save(_job(message_id, "job-2", "pending"))

    fetched = await repository.get_by_message_id(message_id)

    assert fetched is not None
    assert fetched.id == "job-2"


async def test_get_by_message_id_returns_none_when_no_job_exists(db_session):
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)

    assert await repository.get_by_message_id("no-such-message") is None


async def test_transition_status_succeeds_when_status_matches_from_status(
    db_session, message_id
):
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)
    await repository.save(_job(message_id, "job-3", "pending"))

    won = await repository.transition_status(
        "job-3", from_status="pending", to_status="downloading"
    )

    assert won is True
    fetched = await repository.get_by_id("job-3")
    assert fetched is not None
    assert fetched.status == "downloading"


async def test_transition_status_fails_when_status_no_longer_matches_from_status(
    db_session, message_id
):
    # PRD.md §75.8: "Webhook duplicado -> no repite transcripción" — two
    # concurrent workers must not both claim the same job.
    repository = SqlAlchemyMediaProcessingJobRepository(db_session)
    await repository.save(_job(message_id, "job-4", "pending"))
    first_worker_won = await repository.transition_status(
        "job-4", from_status="pending", to_status="downloading"
    )

    second_worker_won = await repository.transition_status(
        "job-4", from_status="pending", to_status="downloading"
    )

    assert first_worker_won is True
    assert second_worker_won is False
