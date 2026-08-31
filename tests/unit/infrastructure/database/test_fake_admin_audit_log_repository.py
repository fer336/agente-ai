from datetime import UTC, datetime

import pytest

from app.domain.entities.admin_audit_log_entry import LOGIN_SUCCESS, AdminAuditLogEntry
from app.domain.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)


def test_fake_admin_audit_log_repository_satisfies_protocol():
    assert isinstance(FakeAdminAuditLogRepository(), AdminAuditLogRepository)


@pytest.mark.asyncio
async def test_save_appends_entry_visible_via_all():
    repository = FakeAdminAuditLogRepository()
    entry = AdminAuditLogEntry(
        id="audit-1",
        admin_user_id="user-1",
        username="tech1",
        action=LOGIN_SUCCESS,
        resource_type=None,
        resource_id=None,
        success=True,
        created_at=datetime.now(UTC),
    )

    await repository.save(entry)

    assert repository.all() == [entry]
