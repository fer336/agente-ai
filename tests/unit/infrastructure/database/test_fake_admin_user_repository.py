from datetime import UTC, datetime

import pytest

from app.domain.entities.admin_user import READ_ONLY, AdminUser
from app.domain.repositories.admin_user_repository import AdminUserRepository
from app.infrastructure.database.fake_admin_user_repository import FakeAdminUserRepository


def _user(id_: str = "user-1", username: str = "tech1", role: str = READ_ONLY) -> AdminUser:
    return AdminUser(
        id=id_,
        username=username,
        password_hash="scrypt$...",
        role=role,
        is_active=True,
        created_at=datetime.now(UTC),
    )


def test_fake_admin_user_repository_satisfies_protocol():
    assert isinstance(FakeAdminUserRepository(), AdminUserRepository)


@pytest.mark.asyncio
async def test_get_by_username_returns_none_when_missing():
    repository = FakeAdminUserRepository()

    assert await repository.get_by_username("missing") is None


@pytest.mark.asyncio
async def test_save_then_get_by_username_round_trips():
    repository = FakeAdminUserRepository()
    user = _user(username="tech1")

    await repository.save(user)

    assert await repository.get_by_username("tech1") == user


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = FakeAdminUserRepository()
    user = _user(id_="user-1")

    await repository.save(user)

    assert await repository.get_by_id("user-1") == user


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = FakeAdminUserRepository()

    assert await repository.get_by_id("missing") is None
