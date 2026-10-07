from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class AppointmentReminderModel(Base):
    """Row shape for durable, idempotent appointment reminder delivery."""

    __tablename__ = "appointment_reminders"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id",
            "kind",
            name="uq_appointment_reminders_appointment_kind",
        ),
        CheckConstraint(
            "kind IN ('confirm_day_before', 'confirm_or_location_same_day', 'review_request')",
            name="ck_appointment_reminders_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'skipped', 'failed')",
            name="ck_appointment_reminders_status",
        ),
        Index("ix_appointment_reminders_due_pending", "status", "due_at"),
        Index("ix_appointment_reminders_patient_review_sent", "patient_id", "kind", "sent_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    appointment_id: Mapped[str] = mapped_column(
        String, ForeignKey("appointments.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_phone: Mapped[str] = mapped_column(String, nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
