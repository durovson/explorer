from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.config import Settings
from app.core.enums import OrderStatus
from app.models.entities import Order
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository
from app.utils.emoji import premium
from app.utils.i18n import restore_language, select_language, tr
from app.utils.media import edit_card

logger = logging.getLogger(__name__)


class OrderNotifier:
    def __init__(
        self, bot: Bot, settings: Settings,
        orders: OrderRepository, users: UserRepository,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._orders = orders
        self._users = users

    async def order_changed(self, order: Order) -> None:
        if not order.bot_chat_id or not order.bot_message_id:
            return
        try:
            user = await self._users.get(order.user_id)
            locale = user.language if user else "ru"
        except Exception:
            locale = "ru"
        token = select_language(locale)
        try:
            await self._notify(order)
        finally:
            restore_language(token)

    async def _notify(self, order: Order) -> None:
        item = (
            f"{order.stars_amount} Stars"
            if order.stars_amount is not None
            else f"Telegram Premium · {order.premium_months} " + tr("мес.", "months")
        )
        info = (
            f"<blockquote>{escape(item)}\n"
            + tr("Получатель: ", "Recipient: ") + f"<b>{escape(order.recipient)}</b>\n"
            + tr("Заказ: ", "Order: ") + f"<code>#{str(order.id)[:8]}</code></blockquote>"
        )
        if order.status is OrderStatus.PAYMENT_CONFIRMED:
            caption = (
                f"{premium('success')} <b>"
                + tr("Платёж подтверждён", "Payment confirmed") + "</b>\n\n"
                + info + "\n\n"
                + f"{premium('pending')} "
                + tr("Заказ передан в исполнение.", "The order has been sent for fulfillment.")
            )
            keyboard = None
        elif order.status is OrderStatus.COMPLETED:
            caption = (
                f"{premium('success')} <b>"
                + tr("Заказ выполнен", "Order completed")
                + "</b>\n\n" + info
            )
            from app.keyboards.menu import completed_keyboard
            keyboard = completed_keyboard()
        elif order.status is OrderStatus.EXPIRED:
            caption = (
                f"{premium('warning')} <b>"
                + tr("Время оплаты истекло", "Payment window expired")
                + "</b>\n\n"
                + tr("Не переводите средства по старым реквизитам.", "Do not send funds to expired payment details.")
            )
            from app.keyboards.menu import expired_keyboard
            keyboard = expired_keyboard()
        elif order.status in {OrderStatus.FAILED, OrderStatus.MANUAL_REVIEW}:
            caption = (
                f"{premium('warning')} <b>"
                + tr("Оплата сохранена, нужна проверка", "Payment saved, review required")
                + "</b>\n\n" + info + "\n\n"
                + tr(
                    "Повторно платить не нужно. Поддержка проверит исполнение.",
                    "Do not pay again. Support will check the fulfillment.",
                )
            )
            from app.keyboards.menu import support_keyboard
            keyboard = support_keyboard(self._settings.SUPPORT_URL)
        else:
            return
        try:
            rendered = await edit_card(
                self._bot, order.bot_chat_id, order.bot_message_id,
                caption, keyboard, "order_status",
            )
            if rendered is not None and rendered.message_id != order.bot_message_id:
                await self._orders.update_bot_message(
                    order.id, rendered.chat.id, rendered.message_id,
                )
        except TelegramBadRequest as exc:
            logger.warning("Could not update order %s notification: %s", order.id, exc)
        except Exception:
            logger.exception("Could not persist order %s notification card", order.id)
