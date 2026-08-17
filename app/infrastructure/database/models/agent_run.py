from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class AgentRunModel(Base):
    """Row shape for the `agent_runs` table (PRD.md §39).

    `error_id` is a plain (non-FK) column — see this change's report: it
    and `errors.agent_run_id` would otherwise form a circular FK between
    these two tables, and the back-reference is informational, not a
    referential-integrity requirement.
    """

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String, ForeignKey("messages.id"), nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_node: Mapped[str | None] = mapped_column(String)
    error_id: Mapped[str | None] = mapped_column(String)
