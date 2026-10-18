from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.enums import OrderStatus
from app.models.entities import Order
from app.utils.i18n import tr
from app.utils.emoji import (
    BACK, CANCEL, COMPLETE, DIAMOND, DOCUMENT, DOCUMENTS, EDIT,
    FAQ, HOME, LANGUAGE, LOCK, NEXT, PAYMENT, PENDING, PREVIOUS,
    REFERRALS, ROBOT, SETTINGS, STAR, USER, USERS, WARNING,
)


def _button(text: str, icon: str | None = None, **kwargs) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **kwargs)


def home_keyboard(support_url: str, admin: bool = False, channel_url: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            _button(tr("Stars", "Stars"), STAR, callback_data="buy:STARS"),
            _button(tr("Premium", "Premium"), DIAMOND, callback_data="buy:PREMIUM"),
        ],
        [
            _button(tr("Покупки", "Purchases"), DOCUMENT, callback_data="orders:0"),
            _button(tr("Рефералы", "Referrals"), REFERRALS, callback_data="referrals"),
        ],
        [
            _button(tr("Поддержка", "Support"), ROBOT, url=support_url),
            _button(tr("Настройки", "Settings"), SETTINGS, callback_data="settings"),
        ],
    ]
    if channel_url:
        rows.append([_button(tr("Канал", "Channel"), DOCUMENT, url=channel_url)])
    if admin:
        rows.append([_button(tr("Админ", "Admin"), LOCK, callback_data="admin:stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_keyboard(username: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        rows.append([
            _button(tr("Себе", "Myself"), USER, callback_data="recipient:self"),
            _button(tr("Другу", "Someone else"), USERS, callback_data="recipient:other"),
        ])
    else:
        rows.append([_button(tr("Другу", "Someone else"), USERS, callback_data="recipient:other")])
    rows.append([_button(tr("Назад", "Back"), BACK, callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_options(product: str, prices: dict[int, str] | None = None) -> InlineKeyboardMarkup:
    if product == "STARS":
        values = (50, 100, 250, 500, 1000, 2500)
        rows = []
        for i in range(0, len(values), 2):
            row = []
            for value in values[i:i + 2]:
                label = f"{value} · {prices[value]} GRAM" if prices and value in prices else str(value)
                row.append(_button(label, STAR, callback_data=f"amount:{value}"))
            rows.append(row)
        rows.append([_button(tr("Ввести своё", "Custom amount"), EDIT, callback_data="amount:custom")])
    else:
        rows = [
            [_button(tr(f"{months} мес.", f"{months} months"), DIAMOND, callback_data=f"months:{months}")]
            for months in (3, 6, 12)
        ]
    rows.append([_button(tr("Назад", "Back"), BACK, callback_data=f"buy:{product}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Оплатить в GRAM", "Pay in GRAM"), PAYMENT, callback_data="currency:TON")],
        [_button(tr("Назад", "Back"), BACK, callback_data="options")],
    ])


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Оплатить", "Pay"), PAYMENT, url=payment_url)],
        [_button(tr("Отмена", "Cancel"), CANCEL, callback_data=f"cancel:{order_id}")],
    ])


def completed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Купить ещё", "Buy more"), STAR, callback_data="shop")],
        [_button(tr("Покупки", "Purchases"), DOCUMENT, callback_data="orders:0")],
    ])


def expired_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Новый заказ", "New order"), STAR, callback_data="shop")],
        [_button(tr("Главное меню", "Main menu"), HOME, callback_data="home")],
    ])


def support_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Поддержка", "Support"), ROBOT, url=url)],
        [_button(tr("Назад", "Back"), BACK, callback_data="home")],
    ])


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Главное меню", "Main menu"), HOME, callback_data="home")]
    ])


def back_to_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Назад", "Back"), BACK, callback_data="options")]
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Язык", "Language"), LANGUAGE, callback_data="settings:language")],
        [
            _button(tr("Документы", "Documents"), DOCUMENTS, callback_data="settings:documents"),
            _button(tr("Помощь и FAQ", "Help & FAQ"), FAQ, callback_data="settings:faq"),
        ],
        [_button(tr("Назад", "Back"), BACK, callback_data="home")],
    ])


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Русский ✓", "Русский"), COMPLETE, callback_data="language:ru")],
        [_button(tr("English", "English ✓"), COMPLETE, callback_data="language:en")],
        [_button(tr("Назад", "Back"), BACK, callback_data="settings")],
    ])


def documents_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Политика конфиденциальности", "Privacy policy"), DOCUMENTS, callback_data="doc:privacy")],
        [_button(tr("Пользовательское соглашение", "User agreement"), DOCUMENTS, callback_data="doc:agreement")],
        [_button(tr("Описание и условия сервиса", "Terms of service"), DOCUMENTS, callback_data="doc:terms")],
        [_button(tr("Назад", "Back"), BACK, callback_data="settings")],
    ])


def document_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Назад", "Back"), BACK, callback_data="settings:documents")],
    ])


def faq_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Назад", "Back"), BACK, callback_data="settings")],
    ])


def _order_button(order: Order, page: int) -> InlineKeyboardButton:
    labels = {
        OrderStatus.COMPLETED: (tr("Завершена", "Completed"), COMPLETE),
        OrderStatus.WAITING_PAYMENT: (tr("Ожидание", "Waiting"), PENDING),
        OrderStatus.PAYMENT_CONFIRMED: (tr("Оплачена", "Paid"), PENDING),
        OrderStatus.PROCESSING: (tr("Обработка", "Processing"), PENDING),
        OrderStatus.EXPIRED: (tr("Истекла", "Expired"), CANCEL),
        OrderStatus.CANCELLED: (tr("Отменена", "Cancelled"), CANCEL),
        OrderStatus.FAILED: (tr("Ошибка", "Failed"), WARNING),
        OrderStatus.MANUAL_REVIEW: (tr("Проверка", "Review"), WARNING),
        OrderStatus.CREATED: (tr("Создана", "Created"), PENDING),
    }
    label, icon = labels.get(order.status, (order.status.value, DOCUMENT))
    return _button(f"{label} | #{str(order.id)[:8]}", icon, callback_data=f"order:{order.id}:{page}")


def orders_keyboard(items: list[Order], page: int, has_next: bool) -> InlineKeyboardMarkup:
    rows = [[_order_button(order, page)] for order in items]
    if page > 0 or has_next:
        nav = []
        if page > 0:
            nav.append(_button("⬅️", PREVIOUS, callback_data=f"orders:{page - 1}"))
        nav.append(_button(f"{page + 1}{'/…' if has_next else '/' + str(page + 1)}", callback_data="page:current"))
        if has_next:
            nav.append(_button("➡️", NEXT, callback_data=f"orders:{page + 1}"))
        rows.append(nav)
    rows.append([_button(tr("Назад", "Back"), BACK, callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_details_keyboard(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(tr("Назад", "Back"), BACK, callback_data=f"orders:{page}")],
        [_button(tr("Главное меню", "Main menu"), HOME, callback_data="home")],
    ])
