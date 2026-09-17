from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class ContactModel(Base):
    """Row shape for the `contacts` table (architecture doc §5.8)."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: `unique=True` matches migration 0017_contacts_phone_unique — added
    #: after a live race let two concurrent webhook deliveries for the same
    #: brand-new phone number silently create two separate contact rows
    #: (see that migration's own docstring).
    phone: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    patient_id: Mapped[str | None] = mapped_column(String, ForeignKey("patients.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
