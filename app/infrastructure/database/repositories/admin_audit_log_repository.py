from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.admin_audit_log_entry import AdminAuditLogEntry
from app.infrastructure.database.models.admin_audit_log_entry import AdminAuditLogModel


class SqlAlchemyAdminAuditLogRepository:
    """`AdminAuditLogRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, entry: AdminAuditLogEntry) -> None:
        model = AdminAuditLogModel(
            id=entry.id,
            admin_user_id=entry.admin_user_id,
            username=entry.username,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            success=entry.success,
            created_at=entry.created_at,
        )
        self._session.add(model)
        await self._session.flush()
