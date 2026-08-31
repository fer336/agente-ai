from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class IncidentModel(Base):
    """Row shape for the `incidents` table (PRD.md §49)."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    error_type: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    affected_conversations: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    linear_issue_id: Mapped[str | None] = mapped_column(String)
    last_notification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
