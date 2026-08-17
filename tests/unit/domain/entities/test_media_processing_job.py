from app.domain.entities.media_processing_job import MediaProcessingJob


def test_creates_media_processing_job_with_all_fields():
    job = MediaProcessingJob(
        id="job-1",
        message_id="msg-1",
        status="pending",
        media_id="media-1",
        media_mime_type="audio/ogg",
        attempts=0,
    )

    assert job.message_id == "msg-1"
    assert job.status == "pending"
    assert job.media_mime_type == "audio/ogg"
    assert job.attempts == 0


def test_media_processing_jobs_with_different_status_are_not_equal():
    first = MediaProcessingJob(
        id="job-2",
        message_id="msg-2",
        status="pending",
        media_id="media-2",
        media_mime_type="audio/ogg",
        attempts=0,
    )
    second = MediaProcessingJob(
        id="job-2",
        message_id="msg-2",
        status="downloading",
        media_id="media-2",
        media_mime_type="audio/ogg",
        attempts=1,
    )

    assert first != second
