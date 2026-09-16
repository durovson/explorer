from app.models.entities import User
from app.repositories.users import UserRepository


class UserService:
    def __init__(self, users: UserRepository):
        self._users = users

    async def ensure(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> User:
        return await self._users.upsert(telegram_id, username, first_name)
