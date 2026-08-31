from typing import Protocol, runtime_checkable

from app.domain.entities.admin_user import AdminUser


@runtime_checkable
class AdminUserRepository(Protocol):
    """Port to durable storage for admin-panel accounts (PRD.md §74.3)."""

    async def get_by_username(self, username: str) -> AdminUser | None: ...

    async def get_by_id(self, admin_user_id: str) -> AdminUser | None: ...

    async def save(self, admin_user: AdminUser) -> None: ...
