from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class ConversationModel(Base):
    """Row shape for the `conversations` table (architecture doc §5.6, §5.8)."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    contact_id: Mapped[str] = mapped_column(String, ForeignKey("contacts.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    # PRD.md §6/§24.2: FREE_INPUT/INTERACTIVE_SELECTION/SENSITIVE_CONFIRMATION/
    # HUMAN — distinct from `mode` (PRD.md §23). See the domain entity's
    # docstring for why these are two separate columns, not one.
    input_state: Mapped[str] = mapped_column(String, nullable=False, server_default="FREE_INPUT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    # Nullable: `None` distinguishes "never handed to a human" / "handed
    # off but staff hasn't replied yet" from an actual timestamped human
    # reply — see the domain entity's docstring for why the lazy timeout
    # in `IngestMessageUseCase` treats those as NOT eligible to auto-expire.
    last_human_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_session_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="1"
    )
    workflow_last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Clean-restart flag: set on `/bot` reactivation or the lazy 1h
    # timeout, consumed (reset to False) by the next agent turn — see the
    # domain entity's docstring.
    awaiting_fresh_restart: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
