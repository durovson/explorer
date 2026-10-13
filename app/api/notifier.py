from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.config import Settings
from app.core.enums import OrderStatus
from app.models.entities import Order
from app.repositories.orders import OrderRepository
from app.utils.emoji import premium
from app.utils.media import edit_card

logger = logging.getLogger(__name__)


class OrderNotifier:
    def __init__(self, bot: Bot, settings: Settings, orders: OrderRepository):
        self._bot = bot
        self._settings = settings
        self._orders = orders

    async def order_changed(self, order: Order) -> None:
        if not order.bot_chat_id or not order.bot_message_id:
            return
        if order.status is OrderStatus.PAYMENT_CONFIRMED:
            screen = "loading"
            caption = (
                f"{premium('success')} <b>Платёж подтверждён</b>\n\n"
                "<blockquote>"
                f"{order.item_label}\nПолучатель: <b>{order.recipient}</b>"
                "</blockquote>\n\n"
                f"{premium('pending')} Заказ передан в исполнение."
            )
            keyboard = None
        elif order.status is OrderStatus.COMPLETED:
            screen = "success"
            caption = (
                f"{premium('success')} <b>Заказ выполнен</b>\n\n"
                "<blockquote>"
                f"{order.item_label}\nПолучатель: <b>{order.recipient}</b>\n"
                f"Заказ: <code>#{str(order.id)[:10]}</code>"
                "</blockquote>"
            )
            from app.keyboards.menu import completed_keyboard

            keyboard = completed_keyboard()
        elif order.status is OrderStatus.EXPIRED:
            screen = "error"
            caption = (
                f"{premium('warning')} <b>Время оплаты истекло</b>\n\n"
                "<blockquote>Не отправляйте средства по старым реквизитам. Создайте новый заказ.</blockquote>"
            )
            from app.keyboards.menu import expired_keyboard

            keyboard = expired_keyboard()
        elif order.status in {OrderStatus.FAILED, OrderStatus.MANUAL_REVIEW}:
            screen = "error"
            caption = (
                f"{premium('warning')} <b>Оплата сохранена, нужна проверка</b>\n\n"
                f"<blockquote>Заказ: <code>#{str(order.id)[:10]}</code>\n"
                "Повторно платить не нужно.</blockquote>\n\n"
                "Поддержка проверит исполнение заказа."
            )
            from app.keyboards.menu import support_keyboard

            keyboard = support_keyboard(self._settings.SUPPORT_URL)
        else:
            return
        try:
            rendered = await edit_card(
                self._bot,
                order.bot_chat_id,
                order.bot_message_id,
                caption,
                keyboard,
                screen,
            )
            if rendered is not None and rendered.message_id != order.bot_message_id:
                await self._orders.update_bot_message(
                    order.id, rendered.chat.id, rendered.message_id
                )
        except TelegramBadRequest as exc:
            logger.warning("Could not update order %s notification: %s", order.id, exc)
        except Exception:
            logger.exception("Could not persist order %s notification card", order.id)
