from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
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
