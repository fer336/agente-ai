from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.entities.admin_audit_log_entry import LOGIN_FAILURE, AdminAuditLogEntry
from app.infrastructure.database.models.admin_audit_log_entry import AdminAuditLogModel
from app.infrastructure.database.repositories.admin_audit_log_repository import (
    SqlAlchemyAdminAuditLogRepository,
)


async def test_save_persists_an_entry_without_a_valid_admin_user_id(db_session):
    repository = SqlAlchemyAdminAuditLogRepository(db_session)
    entry = AdminAuditLogEntry(
        id="audit-1",
        admin_user_id=None,
        username="unknown-user",
        action=LOGIN_FAILURE,
        resource_type=None,
        resource_id=None,
        success=False,
        created_at=datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
    )

    await repository.save(entry)

    result = await db_session.execute(
        select(AdminAuditLogModel).where(AdminAuditLogModel.id == "audit-1")
    )
    model = result.scalar_one()
    assert model.username == "unknown-user"
    assert model.success is False
    assert model.admin_user_id is None
