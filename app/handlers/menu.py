from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.keyboards.menu import back_home, home_keyboard, orders_keyboard
from app.models.entities import Order, User
from app.repositories.orders import OrderRepository
from app.services.referrals import ReferralService
from app.utils.media import render_card, send_card

router = Router(name="menu")


def _home_text() -> str:
    return (
        "<b>Stars & Premium</b>\n\n"
        "Покупка Telegram Stars и Premium через Fragment.\n\n"
        "💎 Оплата только TON или USDT в сети TON.\n"
        "Каждый заказ оплачивается отдельной прямой транзакцией — "
        "внутреннего баланса нет."
    )


@router.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject,
    db_user: User,
    settings: Settings,
    referrals: ReferralService,
    state: FSMContext,
) -> None:
    await state.clear()
    argument = (command.args or "").strip()
    if argument.startswith("ref_"):
        try:
            await referrals.assign(
                db_user.telegram_id, int(argument.removeprefix("ref_"))
            )
        except ValueError:
            pass
    await send_card(
        message,
        _home_text(),
        home_keyboard(settings.SUPPORT_URL, db_user.telegram_id in settings.admin_ids),
        "main_menu",
    )


@router.callback_query(F.data.in_({"home", "shop"}))
async def home(
    callback: CallbackQuery, db_user: User, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    if callback.message:
        await render_card(
            callback.message,
            _home_text(),
            home_keyboard(
                settings.SUPPORT_URL, db_user.telegram_id in settings.admin_ids
            ),
            "main_menu",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("orders:"))
async def orders(
    callback: CallbackQuery, db_user: User, order_repository: OrderRepository
) -> None:
    page = max(0, int((callback.data or "orders:0").split(":", 1)[1]))
    items, has_next = await order_repository.list_for_user(db_user.telegram_id, page)
    lines = ["<b>📋 Мои заказы</b>", ""]
    if not items:
        lines.append("Заказов пока нет.")
    for order in items:
        lines.extend([_order_line(order), ""])
    if callback.message:
        await render_card(
            callback.message,
            "\n".join(lines).rstrip(),
            orders_keyboard(page, has_next),
            "orders",
        )
    await callback.answer()


def _order_line(order: Order) -> str:
    amount = format(order.amount, "f").rstrip("0").rstrip(".")
    return (
        f"<code>{str(order.id)[:8]}</code> · {escape(order.item_label)} → "
        f"<b>{escape(order.recipient)}</b>\n"
        f"{amount} {order.currency.value} · {order.status.value}"
    )


@router.callback_query(F.data == "referrals")
async def referrals_screen(
    callback: CallbackQuery,
    db_user: User,
    referrals: ReferralService,
    settings: Settings,
) -> None:
    stats = await referrals.stats(db_user.telegram_id)
    username = (
        settings.TELEGRAM_BOT_USERNAME
        or (await callback.bot.get_me()).username
        or "YourBot"
    )
    link = f"https://t.me/{username}?start=ref_{db_user.telegram_id}"
    text = (
        "<b>🎁 Друзья</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: <b>{stats.invited}</b>\n"
        f"Оплаченных заказов: <b>{stats.paid_orders}</b>\n"
        f"Выплачено напрямую: <b>{stats.paid_ton} TON</b> / "
        f"<b>{stats.paid_usdt} USDT</b>\n\n"
        "У бота нет реферального баланса: каждая награда учитывается "
        "и выплачивается отдельной транзакцией."
    )
    if callback.message:
        await render_card(callback.message, text, back_home(), "referrals")
    await callback.answer()


@router.callback_query(F.data.in_({"about", "settings"}))
async def info(callback: CallbackQuery) -> None:
    if callback.data == "about":
        text = (
            "<b>🚀 О проекте</b>\n\n"
            "Заказ создается в Supabase, платеж подтверждается в блокчейне TON, "
            "после чего бот автоматически отправляет покупку в Fragment."
        )
        screen = "settings"
    else:
        text = (
            "<b>⚙ Настройки</b>\n\n"
            "В этой версии нет внутреннего баланса, пополнения и "
            "сохраненных платежных реквизитов."
        )
        screen = "settings"
    if callback.message:
        await render_card(callback.message, text, back_home(), screen)
    await callback.answer()
