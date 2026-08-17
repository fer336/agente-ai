from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class ErrorModel(Base):
    """Row shape for the `errors` table (PRD.md §42)."""

    __tablename__ = "errors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String, ForeignKey("conversations.id"))
    agent_run_id: Mapped[str | None] = mapped_column(String, ForeignKey("agent_runs.id"))
    source: Mapped[str] = mapped_column(String, nullable=False)
    error_type: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    technical_detail: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
