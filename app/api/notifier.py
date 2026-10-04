from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.config import Settings
from app.core.enums import OrderProvider, OrderStatus
from app.models.entities import Order
from app.utils.media import edit_card

logger = logging.getLogger(__name__)


class OrderNotifier:
    def __init__(self, bot: Bot, settings: Settings):
        self._bot = bot
        self._settings = settings

    async def order_changed(self, order: Order) -> None:
        if not order.bot_chat_id or not order.bot_message_id:
            return
        provider = "Fragment" if order.provider is OrderProvider.FRAGMENT else "Marketapp"
        if order.status is OrderStatus.PAYMENT_CONFIRMED:
            screen = "loading"
            caption = (
                "✅ <b>Платеж подтвержден в блокчейне</b>\n\n"
                f"{order.item_label} для <b>{order.recipient}</b>\n\n"
                f"Исполняем через {provider}…"
            )
            keyboard = None
        elif order.status is OrderStatus.COMPLETED:
            screen = "success"
            tx_line = (
                f"\nTX: <code>{order.provider_tx_hash[:18]}…</code>"
                if order.provider_tx_hash
                else ""
            )
            caption = (
                "✅ <b>Заказ выполнен</b>\n\n"
                f"{order.item_label}\nПолучатель: <b>{order.recipient}</b>\n\n"
                f"Заказ: <code>{str(order.id)[:8]}</code>{tx_line}"
            )
            from app.keyboards.menu import completed_keyboard

            keyboard = completed_keyboard()
        elif order.status is OrderStatus.EXPIRED:
            screen = "error"
            caption = (
                "⌛ <b>Время оплаты истекло</b>\n\n"
                "Не отправляйте средства по старым реквизитам. Создайте новый заказ."
            )
            from app.keyboards.menu import expired_keyboard

            keyboard = expired_keyboard()
        elif order.status in {OrderStatus.FAILED, OrderStatus.MANUAL_REVIEW}:
            screen = "error"
            caption = (
                "⚠️ <b>Оплата сохранена, нужна проверка</b>\n\n"
                f"Заказ: <code>{order.id}</code>\n"
                f"Провайдер: <b>{provider}</b>\n"
                "Повторно платить не нужно. Поддержка проверит исполнение и blockchain TX."
            )
            from app.keyboards.menu import support_keyboard

            keyboard = support_keyboard(self._settings.SUPPORT_URL)
        else:
            return
        try:
            await edit_card(
                self._bot,
                order.bot_chat_id,
                order.bot_message_id,
                caption,
                keyboard,
                screen,
            )
        except TelegramBadRequest as exc:
            logger.warning("Could not update order %s notification: %s", order.id, exc)
