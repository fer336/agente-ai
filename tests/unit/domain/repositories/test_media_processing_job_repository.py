from app.domain.repositories.media_processing_job_repository import MediaProcessingJobRepository


class ConformingMediaProcessingJobRepository:
    async def get_by_id(self, job_id):
        return None

    async def get_by_message_id(self, message_id):
        return None

    async def save(self, job):
        return None

    async def transition_status(self, job_id, *, from_status, to_status):
        return False


class PartialMediaProcessingJobRepository:
    async def get_by_id(self, job_id):
        return None

    async def save(self, job):
        return None


def test_conforming_class_satisfies_media_processing_job_repository_protocol():
    assert isinstance(ConformingMediaProcessingJobRepository(), MediaProcessingJobRepository)


def test_partial_class_does_not_satisfy_media_processing_job_repository_protocol():
    assert not isinstance(PartialMediaProcessingJobRepository(), MediaProcessingJobRepository)
