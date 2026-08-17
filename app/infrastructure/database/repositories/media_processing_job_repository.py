from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.media_processing_job import MediaProcessingJob
from app.infrastructure.database.models.media_processing_job import MediaProcessingJobModel


class SqlAlchemyMediaProcessingJobRepository:
    """`MediaProcessingJobRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, job_id: str) -> MediaProcessingJob | None:
        model = await self._session.get(MediaProcessingJobModel, job_id)
        if model is None:
            return None
        return _to_entity(model)

    async def get_by_message_id(self, message_id: str) -> MediaProcessingJob | None:
        result = await self._session.execute(
            select(MediaProcessingJobModel).where(
                MediaProcessingJobModel.message_id == message_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, job: MediaProcessingJob) -> None:
        model = await self._session.get(MediaProcessingJobModel, job.id)
        if model is None:
            model = MediaProcessingJobModel(id=job.id)
            self._session.add(model)

        model.message_id = job.message_id
        model.status = job.status
        model.media_id = job.media_id
        model.media_mime_type = job.media_mime_type
        model.attempts = job.attempts
        await self._session.flush()

    async def transition_status(self, job_id: str, *, from_status: str, to_status: str) -> bool:
        result = await self._session.execute(
            update(MediaProcessingJobModel)
            .where(
                MediaProcessingJobModel.id == job_id,
                MediaProcessingJobModel.status == from_status,
            )
            .values(status=to_status)
        )
        await self._session.flush()
        return cast("CursorResult[Any]", result).rowcount == 1


def _to_entity(model: MediaProcessingJobModel) -> MediaProcessingJob:
    return MediaProcessingJob(
        id=model.id,
        message_id=model.message_id,
        status=model.status,
        media_id=model.media_id,
        media_mime_type=model.media_mime_type,
        attempts=model.attempts,
    )
