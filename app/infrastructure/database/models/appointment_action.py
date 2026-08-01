from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class AppointmentActionModel(Base):
    """Row shape for the `appointment_actions` table (architecture doc §12.2)."""

    __tablename__ = "appointment_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    appointment_id: Mapped[str] = mapped_column(
        String, ForeignKey("appointments.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
