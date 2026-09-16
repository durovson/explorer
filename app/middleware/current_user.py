from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.services.users import UserService


class CurrentUserMiddleware(BaseMiddleware):
    def __init__(self, users: UserService):
        self._users = users

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is not None:
            data["db_user"] = await self._users.ensure(
                tg_user.id, tg_user.username, tg_user.first_name
            )
        return await handler(event, data)
