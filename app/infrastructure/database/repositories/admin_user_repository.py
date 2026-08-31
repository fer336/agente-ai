from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.admin_user import AdminUser
from app.infrastructure.database.models.admin_user import AdminUserModel


class SqlAlchemyAdminUserRepository:
    """`AdminUserRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> AdminUser | None:
        result = await self._session.execute(
            select(AdminUserModel).where(AdminUserModel.username == username)
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None

    async def get_by_id(self, admin_user_id: str) -> AdminUser | None:
        model = await self._session.get(AdminUserModel, admin_user_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, admin_user: AdminUser) -> None:
        model = await self._session.get(AdminUserModel, admin_user.id)
        if model is None:
            model = AdminUserModel(id=admin_user.id)
            self._session.add(model)

        model.username = admin_user.username
        model.password_hash = admin_user.password_hash
        model.role = admin_user.role
        model.is_active = admin_user.is_active
        model.created_at = admin_user.created_at
        await self._session.flush()


def _to_entity(model: AdminUserModel) -> AdminUser:
    return AdminUser(
        id=model.id,
        username=model.username,
        password_hash=model.password_hash,
        role=model.role,
        is_active=model.is_active,
        created_at=model.created_at,
    )
