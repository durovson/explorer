from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.core.enums import OrderStatus
from app.keyboards.menu import (
    back_home,
    document_back_keyboard,
    documents_keyboard,
    faq_keyboard,
    home_keyboard,
    language_keyboard,
    order_details_keyboard,
    orders_keyboard,
    settings_keyboard,
)
from app.models.entities import Order, ShopStats, User
from app.repositories.orders import OrderRepository
from app.services.referrals import ReferralService
from app.utils.emoji import premium
from app.utils.media import render_card, send_card

router = Router(name="menu")


def _fmt(value: Decimal, places: int = 9) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def _home_text(stats: ShopStats) -> str:
    started_at = stats.started_at or datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    days = max(1, (datetime.now(UTC).date() - started_at.date()).days + 1)
    stars = f"{stats.stars_sold:,}".replace(",", " ")
    usd = f"{stats.volume_usd:.2f}"
    return (
        f"{premium('sparkles')} <b>Добро пожаловать в STRS | TG!</b>\n\n"
        "<b>Stars и Telegram Premium — быстро и без лишних шагов.</b>\n\n"
        "<blockquote expandable>"
        f"{premium('star')} <b>Stars:</b> отправка прямо на @username.\n\n"
        f"{premium('diamond')} <b>Premium:</b> выбираете срок и получателя.\n\n"
        f"{premium('payment')} <b>Оплата:</b> TON, точная сумма и уникальный Memo.\n\n"
        f"{premium('success')} <b>Автоматически:</b> после подтверждения платежа заказ уходит в исполнение."
        "</blockquote>\n\n"
        f"{premium('coin')} <b>До 25% дешевле, чем покупка внутри Telegram.</b>\n\n"
        f"{premium('calendar')} Бот работает <b>{days}</b> дн. · "
        f"куплено <b>{stars}</b> Stars · оборот <b>{usd}$</b>."
    )


async def _stats(order_repository: OrderRepository) -> ShopStats:
    try:
        return await order_repository.shop_stats()
    except Exception:
        return ShopStats(started_at=datetime.now(UTC))


@router.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject,
    db_user: User,
    settings: Settings,
    referrals: ReferralService,
    order_repository: OrderRepository,
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
        _home_text(await _stats(order_repository)),
        home_keyboard(settings.SUPPORT_URL, db_user.telegram_id in settings.admin_ids),
        "main_menu",
    )


@router.callback_query(F.data.in_({"home", "shop"}))
async def home(
    callback: CallbackQuery,
    db_user: User,
    settings: Settings,
    order_repository: OrderRepository,
    state: FSMContext,
) -> None:
    await state.clear()
    if callback.message:
        await render_card(
            callback.message,
            _home_text(await _stats(order_repository)),
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
    if items:
        text = (
            f"{premium('document')} <b>Мои заказы</b>\n\n"
            "<blockquote>Выберите заказ, чтобы открыть детали и текущий статус.</blockquote>"
        )
    else:
        text = (
            f"{premium('document')} <b>Мои заказы</b>\n\n"
            "<blockquote>Здесь появится история ваших покупок. Пока заказов нет.</blockquote>"
        )
    if callback.message:
        await render_card(
            callback.message,
            text,
            orders_keyboard(items, page, has_next),
            "orders",
        )
    await callback.answer()


def _status_text(status: OrderStatus) -> str:
    return {
        OrderStatus.CREATED: "Создан",
        OrderStatus.WAITING_PAYMENT: "Ожидает оплату",
        OrderStatus.PAYMENT_CONFIRMED: "Оплата подтверждена",
        OrderStatus.PROCESSING: "В обработке",
        OrderStatus.COMPLETED: "Завершён",
        OrderStatus.EXPIRED: "Истёк",
        OrderStatus.CANCELLED: "Отменён",
        OrderStatus.FAILED: "Ошибка",
        OrderStatus.MANUAL_REVIEW: "На проверке",
    }.get(status, status.value)


@router.callback_query(F.data.startswith("order:"))
async def order_details(
    callback: CallbackQuery, db_user: User, order_repository: OrderRepository
) -> None:
    try:
        _, raw_id, raw_page = (callback.data or "").split(":", 2)
        page = max(0, int(raw_page))
        order = await order_repository.get_for_user(UUID(raw_id), db_user.telegram_id)
    except (ValueError, TypeError):
        order = None
        page = 0
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    paid_at = order.paid_at.strftime("%d.%m.%Y %H:%M UTC") if order.paid_at else "—"
    completed_at = (
        order.completed_at.strftime("%d.%m.%Y %H:%M UTC")
        if order.completed_at
        else "—"
    )
    text = (
        f"{premium('document')} <b>Заказ #{str(order.id)[:10]}</b>\n\n"
        "<b>Детали:</b>\n"
        "<blockquote>"
        f"• <b>Товар:</b> {escape(order.item_label)}\n"
        f"• <b>Получатель:</b> {escape(order.recipient)}\n"
        f"• <b>Сумма:</b> {_fmt(order.amount, 3)} {order.currency.value}\n"
        f"• <b>Memo:</b> <code>{escape(order.memo)}</code>"
        "</blockquote>\n\n"
        f"<b>Статус:</b> {_status_text(order.status)} {premium('success') if order.status is OrderStatus.COMPLETED else ''}\n\n"
        "<b>Время:</b>\n"
        f"<blockquote>• Оплачен: {paid_at}\n• Завершён: {completed_at}</blockquote>"
    )
    if callback.message:
        await render_card(
            callback.message,
            text,
            order_details_keyboard(page),
            "orders",
        )
    await callback.answer()


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
    rate = stats.reward_rate * Decimal("100")
    level = "Special" if rate >= Decimal("50") else "Standard"
    text = (
        f"{premium('users')} <b>Рефералы</b>\n\n"
        "<b>Детали:</b>\n"
        "<blockquote>"
        f"• <b>Уровень:</b> {level}\n"
        f"• <b>Реферальный процент:</b> {_fmt(rate, 2)}%\n"
        f"• <b>Приглашено:</b> {stats.invited}\n"
        f"• <b>Завершённых покупок друзей:</b> {stats.paid_orders}"
        "</blockquote>\n\n"
        "<b>Выплачено:</b>\n"
        "<blockquote>"
        f"• TON: {_fmt(stats.paid_ton)}\n"
        f"• USDT: {_fmt(stats.paid_usdt, 6)}"
        "</blockquote>\n\n"
        "<b>Ваша реферальная ссылка:</b>\n"
        f"<code>{link}</code>"
    )
    if callback.message:
        await render_card(callback.message, text, back_home(), "referrals")
    await callback.answer()


@router.callback_query(F.data == "settings")
async def settings_screen(callback: CallbackQuery) -> None:
    text = (
        f"{premium('settings')} <b>Настройки</b>\n\n"
        "<blockquote>Язык интерфейса, документы сервиса и ответы на частые вопросы.</blockquote>"
    )
    if callback.message:
        await render_card(callback.message, text, settings_keyboard(), "settings")
    await callback.answer()


@router.callback_query(F.data == "settings:language")
async def language_screen(callback: CallbackQuery) -> None:
    text = (
        f"{premium('language')} <b>Язык</b>\n\n"
        "Выберите язык интерфейса.\n"
        "<blockquote>Русский язык доступен. Подключение English пока в разработке.</blockquote>"
    )
    if callback.message:
        await render_card(callback.message, text, language_keyboard(), "settings")
    await callback.answer()


@router.callback_query(F.data == "language:ru")
async def language_ru(callback: CallbackQuery) -> None:
    if callback.message:
        await render_card(
            callback.message,
            f"{premium('success')} <b>Язык успешно установлен!</b>",
            back_home(),
            "settings",
        )
    await callback.answer()


@router.callback_query(F.data == "language:en")
async def language_en(callback: CallbackQuery) -> None:
    await callback.answer("English будет добавлен позже", show_alert=True)


@router.callback_query(F.data == "settings:documents")
async def documents_screen(callback: CallbackQuery) -> None:
    text = (
        f"{premium('documents')} <b>Документы</b>\n\n"
        "Выберите документ:\n"
        "<blockquote>Основные правила использования STRS | TG собраны прямо в боте.</blockquote>"
    )
    if callback.message:
        await render_card(callback.message, text, documents_keyboard(), "settings")
    await callback.answer()


_DOCUMENTS = {
    "privacy": (
        "Политика конфиденциальности",
        "STRS | TG хранит только данные, необходимые для работы заказа: Telegram ID, username, данные покупки и технический статус оплаты. "
        "Платёжные seed-фразы и ключи пользователей бот не запрашивает. Данные используются для исполнения заказов, поддержки и предотвращения повторной обработки платежей.",
    ),
    "agreement": (
        "Пользовательское соглашение",
        "Создавая заказ, пользователь подтверждает корректность @username получателя, выбранного товара и суммы. Перевод должен быть выполнен по реквизитам конкретного активного заказа с точным Memo. "
        "Не отправляйте средства по истёкшим или отменённым заказам.",
    ),
    "terms": (
        "Описание и условия сервиса",
        "STRS | TG автоматизирует покупку Telegram Stars и Telegram Premium. Цена фиксируется при создании заказа на ограниченное время и включает стоимость исполнения и сервисную комиссию. "
        "После подтверждения оплаты заказ автоматически передаётся в исполнение; при неоднозначном результате он переводится на ручную проверку без повторного списания.",
    ),
}


@router.callback_query(F.data.startswith("doc:"))
async def document(callback: CallbackQuery) -> None:
    key = (callback.data or "doc:").split(":", 1)[1]
    data = _DOCUMENTS.get(key)
    if data is None:
        await callback.answer("Документ не найден", show_alert=True)
        return
    title, body = data
    text = (
        f"{premium('documents')} <b>{title}</b>\n\n"
        f"<blockquote expandable>{body}</blockquote>"
    )
    if callback.message:
        await render_card(
            callback.message, text, document_back_keyboard(), "settings"
        )
    await callback.answer()


@router.callback_query(F.data == "settings:faq")
async def faq(callback: CallbackQuery) -> None:
    text = (
        f"{premium('help')} <b>Помощь и часто задаваемые вопросы</b>\n\n"
        "<b>1. Как проходит покупка?</b>\n"
        "<blockquote expandable>Выберите Stars или Premium, укажите получателя и оплатите точную сумму TON. После подтверждения блокчейна заказ исполняется автоматически.</blockquote>\n\n"
        "<b>2. Зачем нужен Memo?</b>\n"
        "<blockquote expandable>Memo связывает конкретный перевод с конкретным заказом. Его нужно передать без изменений.</blockquote>\n\n"
        "<b>3. Как рассчитывается сумма?</b>\n"
        "<blockquote expandable>Цена Marketapp увеличивается на фиксированную комиссию. Платёж фиксируется с точностью до 0.000000001 TON, без округления вверх до 0.001.</blockquote>\n\n"
        "<b>4. Что делать, если заказ на проверке?</b>\n"
        "<blockquote expandable>Не платите повторно. Система сохраняет платёж и переводит неоднозначный результат на ручную проверку.</blockquote>"
    )
    if callback.message:
        await render_card(callback.message, text, faq_keyboard(), "settings")
    await callback.answer()
