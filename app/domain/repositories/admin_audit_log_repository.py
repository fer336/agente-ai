from typing import Protocol, runtime_checkable

from app.domain.entities.admin_audit_log_entry import AdminAuditLogEntry


@runtime_checkable
class AdminAuditLogRepository(Protocol):
    """Port to durable storage for the admin panel's audit trail (PRD.md §74.3)."""

    async def save(self, entry: AdminAuditLogEntry) -> None: ...
