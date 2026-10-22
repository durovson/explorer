from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.core.enums import OrderStatus
from app.keyboards.menu import (
    back_home, document_back_keyboard, documents_keyboard, faq_keyboard,
    home_keyboard, language_keyboard, order_details_keyboard, orders_keyboard,
    settings_keyboard,
)
from app.models.entities import ShopStats, User
from app.repositories.orders import OrderRepository
from app.services.referrals import ReferralService
from app.services.users import UserService
from app.utils.emoji import premium
from app.utils.i18n import select_language, tr
from app.utils.media import render_card, send_card

router = Router(name="menu")

class ReferralInput(StatesGroup):
    wallet = State()


def _fmt(value: Decimal, places: int = 9) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".") or "0"


def _home_text(stats: ShopStats) -> str:
    started = stats.started_at or datetime.now(UTC)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    days = max(1, (datetime.now(UTC).date() - started.date()).days + 1)
    stars = f"{stats.stars_sold:,}".replace(",", " ")
    usd = f"{stats.volume_usd:.2f}"
    return (
        tr("<b>Добро пожаловать в STRS | TG!</b>", "<b>Welcome to STRS | TG!</b>")
        + "\n\n"
        + tr(
            "Здесь вы можете купить Telegram Stars и Premium без KYC.",
            "Buy Telegram Stars and Premium here without KYC.",
        )
        + "\n\n"
        + f"{premium('sparkles')} "
        + tr("<b>До 25% дешевле, чем в Telegram!</b>", "<b>Up to 25% cheaper than in Telegram!</b>")
        + "\n\n"
        + f"{premium('calendar')} "
        + tr(
            f"Бот работает <b>{days}</b> дн. За это время куплено <b>{stars}</b> Stars на сумму <b>{usd}$</b>.",
            f"The bot has been running for <b>{days}</b> days. <b>{stars}</b> Stars purchased, totaling <b>${usd}</b>.",
        )
    )


async def _stats(repo: OrderRepository) -> ShopStats:
    try:
        return await repo.shop_stats()
    except Exception:
        return ShopStats(started_at=datetime.now(UTC))


def _home_keyboard(settings: Settings, user: User):
    return home_keyboard(settings.SUPPORT_URL, user.telegram_id in settings.admin_ids, settings.CHANNEL_URL)


@router.message(CommandStart())
async def start(
    message: Message, command: CommandObject, db_user: User,
    settings: Settings, referrals: ReferralService,
    order_repository: OrderRepository, state: FSMContext,
) -> None:
    await state.clear()
    argument = (command.args or "").strip()
    if argument.startswith("ref_"):
        try:
            await referrals.assign(db_user.telegram_id, int(argument.removeprefix("ref_")))
        except ValueError:
            pass
    await send_card(message, _home_text(await _stats(order_repository)), _home_keyboard(settings, db_user), "main_menu")


@router.callback_query(F.data.in_({"home", "shop"}))
async def home(
    callback: CallbackQuery, db_user: User, settings: Settings,
    order_repository: OrderRepository, state: FSMContext,
) -> None:
    await state.clear()
    if callback.message:
        await render_card(callback.message, _home_text(await _stats(order_repository)),
                          _home_keyboard(settings, db_user), "main_menu")
    await callback.answer()


@router.callback_query(F.data == "page:current")
async def page_current(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("orders:"))
async def orders(callback: CallbackQuery, db_user: User, order_repository: OrderRepository) -> None:
    try:
        page = min(1000, max(0, int((callback.data or "orders:0").split(":", 1)[1])))
    except ValueError:
        page = 0
    total = await order_repository.count_for_user(db_user.telegram_id)
    total_pages = max(1, (total + 4) // 5)
    page = min(page, total_pages - 1)
    items, has_next = await order_repository.list_for_user(db_user.telegram_id, page)
    text = f"{premium('document')} <b>" + tr("Покупки:", "Purchases:") + "</b>"
    text += "\n" + tr("Всего: ", "Total: ") + str(total) + f" · {page + 1}/{total_pages}"
    if not items:
        text += "\n\n" + tr("Пока нет покупок.", "No purchases yet.")
    if callback.message:
        await render_card(callback.message, text, orders_keyboard(items, page, has_next, total_pages), "orders")
    await callback.answer()


def _status_text(status: OrderStatus) -> str:
    labels = {
        OrderStatus.CREATED: ("Создан", "Created"),
        OrderStatus.WAITING_PAYMENT: ("Ожидает оплату", "Awaiting payment"),
        OrderStatus.PAYMENT_CONFIRMED: ("Оплачен", "Paid"),
        OrderStatus.PROCESSING: ("Исполняется", "Processing"),
        OrderStatus.COMPLETED: ("Завершён", "Completed"),
        OrderStatus.EXPIRED: ("Истёк", "Expired"),
        OrderStatus.CANCELLED: ("Отменён", "Cancelled"),
        OrderStatus.FAILED: ("Ошибка", "Failed"),
        OrderStatus.MANUAL_REVIEW: ("На проверке", "Under review"),
    }
    ru, en = labels.get(status, (status.value, status.value))
    return tr(ru, en)


@router.callback_query(F.data.startswith("order:"))
async def order_details(callback: CallbackQuery, db_user: User, order_repository: OrderRepository) -> None:
    try:
        _, raw_id, raw_page = (callback.data or "").split(":", 2)
        page = min(1000, max(0, int(raw_page)))
        order = await order_repository.get_for_user(UUID(raw_id), db_user.telegram_id)
    except (ValueError, TypeError):
        order, page = None, 0
    if order is None:
        await callback.answer(tr("Заказ не найден", "Order not found"), show_alert=True)
        return
    item = f"{order.stars_amount} Stars" if order.stars_amount is not None else f"Telegram Premium · {order.premium_months} " + tr("мес.", "months")
    price = _fmt(order.amount, 9 if order.currency.value == "TON" else 6)
    currency_label = "GRAM" if order.currency.value == "TON" else order.currency.value
    details = "\n".join((
        "• " + escape(item),
        "• " + tr("Получатель: ", "Recipient: ") + escape(order.recipient),
        "• " + tr("Сумма: ", "Amount: ") + f"{price} {currency_label}",
        "• Memo: " + f"<code>{escape(order.memo)}</code>",
    ))
    status_label = _status_text(order.status)
    provider_hash = order.fragment_order_id or ""
    if order.status is OrderStatus.COMPLETED and re.fullmatch(r"[0-9a-fA-F]{64}", provider_hash):
        status_label = f'<a href="https://tonviewer.com/transaction/{provider_hash}">{escape(status_label)}</a>'
    text = (
        f"{premium('document')} <b>" + tr("Заказ", "Order") + f" #{str(order.id)[:8]}</b>\n\n"
        + tr("<b>Детали:</b>", "<b>Details:</b>") + f"\n<blockquote>{details}</blockquote>\n\n"
        + tr("<b>Статус:</b> ", "<b>Status:</b> ") + status_label
        + (" " + premium("success") if order.status is OrderStatus.COMPLETED else "")
    )
    if callback.message:
        await render_card(callback.message, text, order_details_keyboard(page), "orders")
    await callback.answer()


@router.callback_query(F.data == "referrals")
async def referrals_screen(
    callback: CallbackQuery, db_user: User, referrals: ReferralService, settings: Settings,
) -> None:
    stats = await referrals.stats(db_user.telegram_id, callback.bot)
    withdrawals = await referrals.withdrawals(db_user.telegram_id)
    username = settings.TELEGRAM_BOT_USERNAME or (await callback.bot.get_me()).username or "YourBot"
    link = f"https://t.me/{username}?start=ref_{db_user.telegram_id}"
    rate = stats.reward_rate * Decimal("100")
    level = stats.level.replace("level_", "Level ").title()
    text = (
        f"{premium('users')} <b>" + tr("Рефералы", "Referrals") + "</b>\n\n"
        + tr("<b>Детали:</b>", "<b>Details:</b>") + "\n<blockquote>"
        + tr("• Уровень: ", "• Level: ") + level + "\n"
        + tr("• Реферальный процент: ", "• Referral rate: ") + _fmt(rate, 2) + "%\n"
        + tr("• Приглашено: ", "• Invited: ") + str(stats.invited) + "\n"
        + tr("• Завершённых покупок друзей: ", "• Friends' completed purchases: ") + str(stats.paid_orders)
        + "\n" + tr("• Оборот: ", "• Turnover: ") + _fmt(stats.ton_volume) + " TON"
        + "</blockquote>\n\n"
        + tr("<b>Доступно к выводу:</b>", "<b>Available:</b>") + f"\n<blockquote>TON: {_fmt(stats.balance_ton)}\nUSDT: {_fmt(stats.balance_usdt,6)}</blockquote>\n"
        + tr("10% от комиссии сервиса; от 500 TON — 20%, от 1000 TON — 30%. Holder 30%, Special 50%. Минимум вывода: 0.1 TON / 1 USDT.",
             "10% of the service fee; from 500 TON — 20%, from 1000 TON — 30%. Holder 30%, Special 50%. Minimum: 0.1 TON / 1 USDT.") + "\n\n"
        + tr("<b>Выплачено:</b>", "<b>Paid out:</b>") + "\n<blockquote>"
        + f"• GRAM: {_fmt(stats.paid_ton)}\n• USDT: {_fmt(stats.paid_usdt, 6)}</blockquote>\n\n"
        + tr("<b>Ваша реферальная ссылка:</b>", "<b>Your referral link:</b>")
        + f"\n<code>{escape(link)}</code>"
        + "\n\n" + "\n".join(f"#{w['id']} · {_fmt(Decimal(str(w['amount'])))} {w['currency']} · {escape(w['status'])}" for w in withdrawals)
    )
    if callback.message:
        markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr("Вывести TON","Withdraw TON"),callback_data="refwithdraw:TON"),InlineKeyboardButton(text=tr("Вывести USDT","Withdraw USDT"),callback_data="refwithdraw:USDT")],
            back_home().inline_keyboard[0],
        ])
        await render_card(callback.message, text, markup, "referrals")
    await callback.answer()


@router.callback_query(F.data.startswith("refwithdraw:"))
async def referral_withdraw(callback: CallbackQuery, state: FSMContext) -> None:
    currency=(callback.data or "").split(":")[-1]
    if currency not in {"TON","USDT"}:
        return
    await state.set_state(ReferralInput.wallet)
    await state.update_data(referral_currency=currency)
    if callback.message:
        await callback.message.answer(tr("Введите свой адрес TON mainnet для вывода ","Enter your TON mainnet wallet for ")+currency,reply_markup=back_home())
    await callback.answer()


@router.message(ReferralInput.wallet)
async def referral_wallet(message: Message, state: FSMContext, referrals: ReferralService) -> None:
    data=await state.get_data()
    try:
        row_id=await referrals.request_withdrawal(message.from_user.id,data.get("referral_currency",""),message.text or "")
    except Exception:
        await message.answer(tr("Не удалось создать вывод: проверьте адрес, минимум 0.1 TON / 1 USDT и отсутствие активной заявки.","Cannot request withdrawal: check wallet, minimum 0.1 TON / 1 USDT and existing requests."))
        return
    await state.clear()
    await message.answer(tr("Заявка на вывод принята: #","Withdrawal requested: #")+str(row_id)+" · creating",reply_markup=back_home())


@router.callback_query(F.data == "settings")
async def settings_screen(callback: CallbackQuery) -> None:
    text = f"{premium('settings')} <b>" + tr("Настройки", "Settings") + "</b>\n\n" + tr(
        "Язык и ответы на вопросы.", "Language and frequently asked questions."
    )
    if callback.message:
        await render_card(callback.message, text, settings_keyboard(), "settings")
    await callback.answer()


@router.callback_query(F.data == "settings:language")
async def language_screen(callback: CallbackQuery) -> None:
    text = f"{premium('language')} <b>" + tr("Язык", "Language") + "</b>\n\n" + tr(
        "Выберите язык интерфейса:", "Choose your interface language:"
    )
    if callback.message:
        await render_card(callback.message, text, language_keyboard(), "settings")
    await callback.answer()


async def _save_language(callback: CallbackQuery, users_service: UserService, value: str) -> None:
    await users_service.set_language(callback.from_user.id, value)
    select_language(value)
    if callback.message:
        await render_card(
            callback.message,
            f"{premium('success')} <b>" + tr("Язык установлен!", "Language saved!") + "</b>",
            language_keyboard(), "settings",
        )
    await callback.answer()


@router.callback_query(F.data == "language:ru")
async def language_ru(callback: CallbackQuery, users_service: UserService) -> None:
    await _save_language(callback, users_service, "ru")


@router.callback_query(F.data == "language:en")
async def language_en(callback: CallbackQuery, users_service: UserService) -> None:
    await _save_language(callback, users_service, "en")


@router.callback_query(F.data == "settings:documents")
async def documents_screen(callback: CallbackQuery) -> None:
    text = f"{premium('documents')} <b>" + tr("Документы", "Documents") + "</b>\n\n" + tr(
        "Выберите документ:", "Select a document:"
    )
    if callback.message:
        await render_card(callback.message, text, documents_keyboard(), "settings")
    await callback.answer()


_DOCUMENTS = {
    "privacy": (
        ("Политика конфиденциальности", "Privacy policy"),
        (
            "STRS | TG хранит необходимые для заказа Telegram ID, username, сведения о покупке и статус оплаты. "
            "Бот не запрашивает seed-фразу вашего кошелька. Данные используются для исполнения заказа и предотвращения повторных платежей.",
            "STRS | TG stores your Telegram ID, username, order details and payment status needed to fulfill purchases. "
            "We never request your wallet recovery phrase. Data is used for fulfillment and duplicate-payment prevention.",
        ),
    ),
    "agreement": (
        ("Пользовательское соглашение", "User agreement"),
        (
            "Проверяйте получателя, товар и сумму перед оплатой. Для платежа требуется точный Memo. "
            "Не переводите средства на истёкшие или отменённые заказы.",
            "Verify the recipient, product and payment amount. The exact Memo is required to identify your transfer. "
            "Do not pay expired or cancelled orders.",
        ),
    ),
    "terms": (
        ("Условия сервиса", "Terms of service"),
        (
            "STRS | TG автоматически приобретает Stars и Premium после подтверждения платежа. "
            "Цена фиксируется при создании заказа и уже включает комиссию. Неопределённые результаты отправляются на проверку без автоматической повторной покупки.",
            "STRS | TG automatically purchases Stars and Premium after payment confirmation. "
            "Your quoted price includes the fee and is fixed when the order is created. Uncertain results are reviewed without an automatic duplicate purchase.",
        ),
    ),
}


@router.callback_query(F.data.startswith("doc:"))
async def document(callback: CallbackQuery) -> None:
    key = (callback.data or "").split(":", 1)[-1]
    data = _DOCUMENTS.get(key)
    if data is None:
        await callback.answer(tr("Документ не найден", "Document not found"), show_alert=True)
        return
    (ru_title, en_title), (ru_body, en_body) = data
    text = f"{premium('documents')} <b>{tr(ru_title, en_title)}</b>\n\n<blockquote expandable>{escape(tr(ru_body, en_body))}</blockquote>"
    if callback.message:
        await render_card(callback.message, text, document_back_keyboard(), "settings")
    await callback.answer()


@router.callback_query(F.data == "settings:faq")
async def faq(callback: CallbackQuery) -> None:
    questions = [
        (
            ("Как проходит покупка?", "How do I purchase?"),
            ("Выберите товар, получателя и оплатите точную сумму с Memo. После подтверждения платежа заказ исполняется автоматически.",
             "Choose a product and recipient. Send the exact payment amount with the Memo. The order is processed automatically after confirmation."),
        ),
        (
            ("Зачем нужен Memo?", "Why is the Memo needed?"),
            ("Memo связывает перевод с заказом. Скопируйте его без изменений.",
             "The Memo links your transfer to the order. Copy it exactly."),
        ),
        (
            ("Как рассчитывается цена?", "How is the price calculated?"),
            ("К цене Marketapp применяется фиксированная наценка. TON рассчитывается с точностью до одного нанотона, без округления вверх.",
             "A fixed markup is applied to the Marketapp price. The TON amount is calculated to one nanotON without rounding up."),
        ),
        (
            ("Что делать, если заказ на проверке?", "What if the order is under review?"),
            ("Не платите повторно. Поддержка проверит статус исполнения.",
             "Do not pay twice. Support will check the fulfillment status."),
        ),
    ]
    text = f"{premium('help')} <b>" + tr("Помощь и FAQ", "Help & FAQ") + "</b>\n\n"
    text += "\n\n".join(
        f"<b>{i}. {tr(ru_q, en_q)}</b>\n<blockquote expandable>{tr(ru_a, en_a)}</blockquote>"
        for i, ((ru_q, en_q), (ru_a, en_a)) in enumerate(questions, 1)
    )
    if callback.message:
        await render_card(callback.message, text, faq_keyboard(), "settings")
    await callback.answer()
