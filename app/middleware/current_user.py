from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.services.users import UserService
from app.utils.i18n import restore_language, select_language


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
        user = (
            await self._users.ensure(tg_user.id, tg_user.username, tg_user.first_name)
            if tg_user is not None
            else None
        )
        if user is not None:
            data["db_user"] = user
        token = select_language(user.language if user else "ru")
        try:
            return await handler(event, data)
        finally:
            restore_language(token)
