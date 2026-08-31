from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class AdminAuditLogModel(Base):
    """Row shape for the `admin_audit_log` table (PRD.md §74.3).

    `admin_user_id` is a plain (non-FK) column, not `ForeignKey("admin_users.id")`
    — a login-failure entry (PRD.md §74.3's "auditoría de accesos") has no
    valid admin user to reference, and the audit trail must outlive an
    account even if it were ever deleted.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    admin_user_id: Mapped[str | None] = mapped_column(String)
    username: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String)
    resource_id: Mapped[str | None] = mapped_column(String)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
