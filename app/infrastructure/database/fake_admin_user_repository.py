from app.domain.entities.admin_user import AdminUser


class FakeAdminUserRepository:
    """In-memory fake implementing `AdminUserRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, AdminUser] = {}

    async def get_by_username(self, username: str) -> AdminUser | None:
        return next(
            (user for user in self._by_id.values() if user.username == username), None
        )

    async def get_by_id(self, admin_user_id: str) -> AdminUser | None:
        return self._by_id.get(admin_user_id)

    async def save(self, admin_user: AdminUser) -> None:
        self._by_id[admin_user.id] = admin_user
