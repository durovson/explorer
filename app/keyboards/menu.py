from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.enums import OrderStatus
from app.models.entities import Order
from app.utils.emoji import (
    BACK,
    CANCEL,
    COMPLETE,
    DIAMOND,
    DOCUMENT,
    DOCUMENTS,
    EDIT,
    FAQ,
    HOME,
    LANGUAGE,
    LOCK,
    NEXT,
    PAYMENT,
    PENDING,
    PREVIOUS,
    REFERRALS,
    ROBOT,
    SETTINGS,
    STAR,
    USER,
    USERS,
    WARNING,
)


def _button(text: str, icon: str | None = None, **kwargs) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, icon_custom_emoji_id=icon, **kwargs)


def home_keyboard(support_url: str, admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _button("Купить Stars", STAR, callback_data="buy:STARS"),
            _button("Купить Premium", DIAMOND, callback_data="buy:PREMIUM"),
        ],
        [
            _button("Мои заказы", DOCUMENT, callback_data="orders:0"),
            _button("Рефералы", REFERRALS, callback_data="referrals"),
        ],
        [
            _button("Поддержка", ROBOT, url=support_url),
            _button("Настройки", SETTINGS, callback_data="settings"),
        ],
    ]
    if admin:
        rows.append([_button("Админ", LOCK, callback_data="admin:stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_keyboard(username: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        rows.append([_button("Себе", USER, callback_data="recipient:self")])
    rows.extend(
        [
            [_button("Другому", USERS, callback_data="recipient:other")],
            [_button("Назад", BACK, callback_data="home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_options(product: str) -> InlineKeyboardMarkup:
    if product == "STARS":
        values = (50, 100, 250, 500, 1000, 2500)
        rows = [
            [
                _button(str(values[i]), STAR, callback_data=f"amount:{values[i]}"),
                _button(
                    str(values[i + 1]),
                    STAR,
                    callback_data=f"amount:{values[i + 1]}",
                ),
            ]
            for i in range(0, len(values), 2)
        ]
        rows.append([_button("Ввести своё", EDIT, callback_data="amount:custom")])
    else:
        rows = [
            [
                _button(
                    f"{months} месяца" if months == 3 else f"{months} месяцев",
                    DIAMOND,
                    callback_data=f"months:{months}",
                )
            ]
            for months in (3, 6, 12)
        ]
    rows.append([_button("Получатель", BACK, callback_data=f"buy:{product}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Оплатить в TON", PAYMENT, callback_data="currency:TON")],
            [_button("Назад", BACK, callback_data="options")],
        ]
    )


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Оплатить через кошелёк", PAYMENT, url=payment_url)],
            [_button("Отменить", CANCEL, callback_data=f"cancel:{order_id}")],
        ]
    )


def completed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Купить ещё", STAR, callback_data="shop")],
            [_button("Мои заказы", DOCUMENT, callback_data="orders:0")],
        ]
    )


def expired_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Создать новый заказ", STAR, callback_data="shop")],
            [_button("Главное меню", HOME, callback_data="home")],
        ]
    )


def support_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Поддержка", ROBOT, url=url)],
            [_button("Главное меню", HOME, callback_data="home")],
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("Главное меню", HOME, callback_data="home")]]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Язык", LANGUAGE, callback_data="settings:language")],
            [
                _button("Документы", DOCUMENTS, callback_data="settings:documents"),
                _button("Помощь и FAQ", FAQ, callback_data="settings:faq"),
            ],
            [_button("Назад", BACK, callback_data="home")],
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Русский — выбран", COMPLETE, callback_data="language:ru")],
            [_button("English — скоро", PENDING, callback_data="language:en")],
            [_button("Назад", BACK, callback_data="settings")],
        ]
    )


def documents_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Политика конфиденциальности", DOCUMENTS, callback_data="doc:privacy")],
            [_button("Пользовательское соглашение", DOCUMENTS, callback_data="doc:agreement")],
            [_button("Описание и условия сервиса", DOCUMENTS, callback_data="doc:terms")],
            [_button("Назад", BACK, callback_data="settings")],
        ]
    )


def document_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Назад к документам", BACK, callback_data="settings:documents")],
                    ]
    )


def faq_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Назад", BACK, callback_data="settings")],
                    ]
    )


def _order_button(order: Order, page: int) -> InlineKeyboardButton:
    labels = {
        OrderStatus.COMPLETED: ("Завершён", COMPLETE),
        OrderStatus.WAITING_PAYMENT: ("Ожидает оплату", PENDING),
        OrderStatus.PAYMENT_CONFIRMED: ("Оплачен", PENDING),
        OrderStatus.PROCESSING: ("В обработке", PENDING),
        OrderStatus.EXPIRED: ("Истёк", CANCEL),
        OrderStatus.CANCELLED: ("Отменён", CANCEL),
        OrderStatus.FAILED: ("Ошибка", WARNING),
        OrderStatus.MANUAL_REVIEW: ("Проверка", WARNING),
        OrderStatus.CREATED: ("Создан", PENDING),
    }
    label, icon = labels.get(order.status, (order.status.value, DOCUMENT))
    return _button(
        f"{label} | #{str(order.id)[:10]}",
        icon,
        callback_data=f"order:{order.id}:{page}",
    )


def orders_keyboard(
    items: list[Order], page: int, has_next: bool
) -> InlineKeyboardMarkup:
    rows = [[_order_button(order, page)] for order in items]
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(_button("Назад", PREVIOUS, callback_data=f"orders:{page - 1}"))
    if has_next:
        navigation.append(_button("Далее", NEXT, callback_data=f"orders:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([_button("Новый заказ", STAR, callback_data="shop")])
    rows.append([_button("Главное меню", HOME, callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_details_keyboard(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("Назад", BACK, callback_data=f"orders:{page}")],
            [_button("Главное меню", HOME, callback_data="home")],
        ]
    )
