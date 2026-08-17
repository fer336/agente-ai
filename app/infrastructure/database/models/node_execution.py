from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class NodeExecutionModel(Base):
    """Row shape for the `node_executions` table (PRD.md §40)."""

    __tablename__ = "node_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.id"), nullable=False)
    node_name: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_id: Mapped[str | None] = mapped_column(String)
