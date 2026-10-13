from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.emoji import (
    BACK,
    CANCEL,
    DIAMOND,
    DOCUMENT,
    EDIT,
    HOME,
    LOCK,
    PAYMENT,
    ROBOT,
    SETTINGS,
    STAR,
    USER,
    USERS,
)


def home_keyboard(support_url: str, admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Купить Stars", icon_custom_emoji_id=STAR, callback_data="buy:STARS"
            ),
            InlineKeyboardButton(
                text="Купить Premium",
                icon_custom_emoji_id=DIAMOND,
                callback_data="buy:PREMIUM",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Мои заказы",
                icon_custom_emoji_id=DOCUMENT,
                callback_data="orders:0",
            ),
            InlineKeyboardButton(
                text="Друзья", icon_custom_emoji_id=USERS, callback_data="referrals"
            ),
        ],
        [
            InlineKeyboardButton(
                text="Поддержка", icon_custom_emoji_id=ROBOT, url=support_url
            ),
            InlineKeyboardButton(
                text="Настройки",
                icon_custom_emoji_id=SETTINGS,
                callback_data="settings",
            ),
        ],
    ]
    if admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Админ", icon_custom_emoji_id=LOCK, callback_data="admin:stats"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_keyboard(username: str | None) -> InlineKeyboardMarkup:
    rows = []
    if username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Себе", icon_custom_emoji_id=USER, callback_data="recipient:self"
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="Другому",
                    icon_custom_emoji_id=USERS,
                    callback_data="recipient:other",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад", icon_custom_emoji_id=BACK, callback_data="home"
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_options(product: str) -> InlineKeyboardMarkup:
    if product == "STARS":
        values = (50, 100, 250, 500, 1000, 2500)
        rows = [
            [
                InlineKeyboardButton(
                    text=str(values[i]),
                    icon_custom_emoji_id=STAR,
                    callback_data=f"amount:{values[i]}",
                ),
                InlineKeyboardButton(
                    text=str(values[i + 1]),
                    icon_custom_emoji_id=STAR,
                    callback_data=f"amount:{values[i + 1]}",
                ),
            ]
            for i in range(0, len(values), 2)
        ]
        rows.append(
            [
                InlineKeyboardButton(
                    text="Ввести своё",
                    icon_custom_emoji_id=EDIT,
                    callback_data="amount:custom",
                )
            ]
        )
    else:
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{months} месяца" if months == 3 else f"{months} месяцев",
                    icon_custom_emoji_id=DIAMOND,
                    callback_data=f"months:{months}",
                )
            ]
            for months in (3, 6, 12)
        ]
    rows.append(
        [
            InlineKeyboardButton(
                text="Получатель",
                icon_custom_emoji_id=BACK,
                callback_data=f"buy:{product}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="TON", icon_custom_emoji_id=DIAMOND, callback_data="currency:TON"
                )
            ],
            [
                InlineKeyboardButton(
                    text="USDT (сеть TON)",
                    icon_custom_emoji_id=PAYMENT,
                    callback_data="currency:USDT",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад", icon_custom_emoji_id=BACK, callback_data="options"
                )
            ],
        ]
    )


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оплатить через кошелёк",
                    icon_custom_emoji_id=PAYMENT,
                    url=payment_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    icon_custom_emoji_id=CANCEL,
                    callback_data=f"cancel:{order_id}",
                )
            ],
        ]
    )


def completed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить ещё", icon_custom_emoji_id=STAR, callback_data="shop"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мои заказы",
                    icon_custom_emoji_id=DOCUMENT,
                    callback_data="orders:0",
                )
            ],
        ]
    )


def expired_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать новый заказ",
                    icon_custom_emoji_id=STAR,
                    callback_data="shop",
                )
            ]
        ]
    )


def support_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Поддержка", icon_custom_emoji_id=ROBOT, url=url)]
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Главное меню", icon_custom_emoji_id=HOME, callback_data="home"
                )
            ]
        ]
    )


def orders_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup:
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="Назад", callback_data=f"orders:{page - 1}")
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(text="Далее", callback_data=f"orders:{page + 1}")
        )
    rows = [navigation] if navigation else []
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="Новый заказ", icon_custom_emoji_id=STAR, callback_data="shop"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню", icon_custom_emoji_id=HOME, callback_data="home"
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
