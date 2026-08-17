from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class MediaProcessingJobModel(Base):
    """Row shape for the `media_processing_jobs` table (PRD.md §24.1, §33).

    PRD.md lists this table by name (§33) and by its place in the inbound-
    audio flow (§24.1: "Crear media_processing_job" right after persisting
    the message), but — unlike `scheduled_actions` (§16.2) — gives it no
    explicit column spec. The columns below are a minimal, self-contained
    job/task-tracking shape mirroring `outbox_events`, sized for the future
    audio worker (not built yet, see PRD §70 Etapa 9.1) to claim and
    process one job per inbound media message.
    """

    __tablename__ = "media_processing_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    media_id: Mapped[str] = mapped_column(String, nullable=False)
    media_mime_type: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
