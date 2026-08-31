from datetime import UTC, datetime

from app.domain.entities.admin_user import ADMIN_TECHNICAL, AdminUser
from app.infrastructure.database.repositories.admin_user_repository import (
    SqlAlchemyAdminUserRepository,
)


def _user(id_: str, username: str) -> AdminUser:
    return AdminUser(
        id=id_,
        username=username,
        password_hash="scrypt$16384$8$1$abc$def",
        role=ADMIN_TECHNICAL,
        is_active=True,
        created_at=datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
    )


async def test_save_then_get_by_username_round_trips(db_session):
    repository = SqlAlchemyAdminUserRepository(db_session)
    user = _user("admin-1", "tech1")

    await repository.save(user)
    fetched = await repository.get_by_username("tech1")

    assert fetched is not None
    assert fetched.id == "admin-1"
    assert fetched.role == ADMIN_TECHNICAL


async def test_get_by_username_returns_none_when_missing(db_session):
    repository = SqlAlchemyAdminUserRepository(db_session)

    assert await repository.get_by_username("missing") is None


async def test_save_then_get_by_id_round_trips(db_session):
    repository = SqlAlchemyAdminUserRepository(db_session)
    user = _user("admin-2", "tech2")

    await repository.save(user)
    fetched = await repository.get_by_id("admin-2")

    assert fetched is not None
    assert fetched.username == "tech2"


async def test_save_upserts_by_id(db_session):
    repository = SqlAlchemyAdminUserRepository(db_session)
    user = _user("admin-3", "tech3")
    await repository.save(user)

    user.is_active = False
    await repository.save(user)

    fetched = await repository.get_by_id("admin-3")
    assert fetched is not None
    assert fetched.is_active is False
