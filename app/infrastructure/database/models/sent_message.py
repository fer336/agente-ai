from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class SentMessageModel(Base):
    """Row shape for the `sent_messages` table — correlates a YCloud
    outbound message id to the conversation it was sent for, see
    `app.domain.entities.sent_message.SentMessage`'s own docstring."""

    __tablename__ = "sent_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
