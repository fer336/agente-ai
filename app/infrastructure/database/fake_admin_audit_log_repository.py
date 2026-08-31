from app.domain.entities.admin_audit_log_entry import AdminAuditLogEntry


class FakeAdminAuditLogRepository:
    """In-memory fake implementing `AdminAuditLogRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._entries: list[AdminAuditLogEntry] = []

    async def save(self, entry: AdminAuditLogEntry) -> None:
        self._entries.append(entry)

    def all(self) -> list[AdminAuditLogEntry]:
        """Test/dev introspection helper — not part of the `AdminAuditLogRepository` Protocol."""
        return list(self._entries)
