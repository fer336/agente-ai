from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class MessageModel(Base):
    """Row shape for the `messages` table (architecture doc §5.8, §12.1;
    media/transcription columns per PRD.md §33, added for the audio
    pipeline, PRD.md §24.1).
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    external_message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    message_type: Mapped[str] = mapped_column(String, nullable=False, server_default="text")
    media_id: Mapped[str | None] = mapped_column(String)
    media_mime_type: Mapped[str | None] = mapped_column(String)
    media_sha256: Mapped[str | None] = mapped_column(String)
    media_status: Mapped[str | None] = mapped_column(String)
    inbound_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcription: Mapped[str | None] = mapped_column(String)
    transcription_status: Mapped[str | None] = mapped_column(String)
    transcription_provider: Mapped[str | None] = mapped_column(String)
    transcription_model: Mapped[str | None] = mapped_column(String)
    transcription_duration_ms: Mapped[int | None] = mapped_column(Integer)
    transcription_error: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
