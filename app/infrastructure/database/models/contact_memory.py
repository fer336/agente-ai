from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class ContactMemoryModel(Base):
    """Row shape for the `contact_memories` table (conversational-memory
    module) — one row per contact, overwritten on each compaction.
    """

    __tablename__ = "contact_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    contact_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    last_compacted_message_id: Mapped[str | None] = mapped_column(String)
    last_compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
