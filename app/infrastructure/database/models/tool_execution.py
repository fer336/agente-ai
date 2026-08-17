from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class ToolExecutionModel(Base):
    """Row shape for the `tool_executions` table (PRD.md §41)."""

    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.id"), nullable=False)
    node_execution_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("node_executions.id")
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    request_summary: Mapped[str] = mapped_column(Text, nullable=False)
    response_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False)
    http_status: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
