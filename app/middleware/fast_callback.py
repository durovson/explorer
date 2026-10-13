from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, TelegramObject, Update

logger = logging.getLogger(__name__)

_EXPIRED_CALLBACK_MARKERS = (
    "query is too old",
    "query id is invalid",
    "response timeout expired",
)

_FAST_EXACT = frozenset(
    {
        "home",
        "shop",
        "referrals",
        "settings",
        "settings:language",
        "settings:documents",
        "settings:faq",
        "language:ru",
        "recipient:other",
        "options",
        "amount:custom",
    }
)
_FAST_PREFIXES = (
    "buy:",
    "orders:",
    "amount:",
    "months:",
)


def callback_from_event(event: TelegramObject) -> CallbackQuery | None:
    if isinstance(event, CallbackQuery):
        return event
    if isinstance(event, Update):
        return event.callback_query
    return None


def is_fast_navigation_callback(callback: CallbackQuery) -> bool:
    data = callback.data or ""
    if data == "recipient:self":
        return bool(callback.from_user.username)
    return data in _FAST_EXACT or data.startswith(_FAST_PREFIXES)


def _expired_callback_error(exc: TelegramBadRequest) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _EXPIRED_CALLBACK_MARKERS)


class FastCallbackMiddleware(BaseMiddleware):
    """Acknowledge safe navigation immediately while rendering continues."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        callback = callback_from_event(event)
        if callback is None or not is_fast_navigation_callback(callback):
            return await handler(event, data)

        ack_task = asyncio.create_task(
            self._acknowledge(callback), name=f"callback-ack:{callback.id}"
        )
        try:
            return await handler(event, data)
        except TelegramBadRequest as exc:
            # Navigation handlers written before fast-ACK may answer the same
            # callback once more after rendering. Telegram rejects that second
            # answer; it is harmless because the first ACK already succeeded.
            if _expired_callback_error(exc):
                return None
            raise
        finally:
            await ack_task

    @staticmethod
    async def _acknowledge(callback: CallbackQuery) -> None:
        try:
            await callback.answer()
        except TelegramBadRequest as exc:
            if not _expired_callback_error(exc):
                logger.warning(
                    "Fast callback ACK rejected for %s: %s", callback.data, exc
                )
        except Exception:
            # A transport issue in the ACK path must never suppress the actual
            # navigation handler.
            logger.warning(
                "Fast callback ACK failed for %s", callback.data, exc_info=True
            )
