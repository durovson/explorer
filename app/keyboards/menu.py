from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def home_keyboard(support_url: str, admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⭐ Stars", callback_data="buy:STARS"),
            InlineKeyboardButton(text="💎 Premium", callback_data="buy:PREMIUM"),
        ],
        [
            InlineKeyboardButton(text="◈ GRAM", callback_data="buy:GRAM"),
            InlineKeyboardButton(text="🎁 Аренда NFT", callback_data="rent:0"),
        ],
        [
            InlineKeyboardButton(text="👛 Кошелёк", callback_data="wallet"),
            InlineKeyboardButton(text="📋 Мои заказы", callback_data="orders:0"),
        ],
        [
            InlineKeyboardButton(text="🎁 Друзья", callback_data="referrals"),
            InlineKeyboardButton(text="⚙ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text="🚀 О проекте", callback_data="about"),
            InlineKeyboardButton(text="💬 Поддержка", url=support_url),
        ],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ", callback_data="admin:stats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_keyboard(username: str | None) -> InlineKeyboardMarkup:
    rows = []
    if username:
        rows.append(
            [InlineKeyboardButton(text="♿ Себе", callback_data="recipient:self")]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="🎁 Другому", callback_data="recipient:other")],
            [InlineKeyboardButton(text="← Назад", callback_data="home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_options(product: str) -> InlineKeyboardMarkup:
    if product == "STARS":
        values = (50, 100, 250, 500, 1000, 2500)
        rows = [
            [
                InlineKeyboardButton(
                    text=f"⭐ {values[i]}", callback_data=f"amount:{values[i]}"
                ),
                InlineKeyboardButton(
                    text=f"⭐ {values[i + 1]}", callback_data=f"amount:{values[i + 1]}"
                ),
            ]
            for i in range(0, len(values), 2)
        ]
        rows.append(
            [InlineKeyboardButton(text="✏ Ввести своё", callback_data="amount:custom")]
        )
    elif product == "PREMIUM":
        rows = [
            [
                InlineKeyboardButton(
                    text=f"💎 {months} месяца"
                    if months == 3
                    else f"💎 {months} месяцев",
                    callback_data=f"months:{months}",
                )
            ]
            for months in (3, 6, 12)
        ]
    else:
        values = (1, 5, 10, 25, 50, 100)
        rows = [
            [
                InlineKeyboardButton(text=f"◈ {values[i]} GRAM", callback_data=f"gram:{values[i]}"),
                InlineKeyboardButton(text=f"◈ {values[i + 1]} GRAM", callback_data=f"gram:{values[i + 1]}"),
            ]
            for i in range(0, len(values), 2)
        ]
        rows.append(
            [InlineKeyboardButton(text="✏ Ввести своё", callback_data="gram:custom")]
        )
    rows.append(
        [InlineKeyboardButton(text="← Получатель", callback_data=f"buy:{product}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currency_keyboard(ton_only: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="💎 TON", callback_data="currency:TON")]]
    if not ton_only:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💵 USDT (сеть TON)", callback_data="currency:USDT"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="options")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оплатить через кошелёк", url=payment_url)],
            [InlineKeyboardButton(text="✕ Отменить", callback_data=f"cancel:{order_id}")],
        ]
    )


def rent_keyboard(page: int, offers_count: int, has_next: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🎁 NFT #{i + 1}", callback_data=f"rentpick:{i}")]
        for i in range(offers_count)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"rent:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"rent:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rent_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Арендовать", callback_data="rentconfirm")],
            [InlineKeyboardButton(text="← Каталог", callback_data="rent:0")],
        ]
    )


def completed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛍 Купить ещё", callback_data="shop")],
            [InlineKeyboardButton(text="📋 Мои заказы", callback_data="orders:0")],
        ]
    )


def expired_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать новый заказ", callback_data="shop")]
        ]
    )


def support_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Поддержка", url=url)]]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Главное меню", callback_data="home")]
        ]
    )


def orders_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup:
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="←", callback_data=f"orders:{page - 1}")
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(text="→", callback_data=f"orders:{page + 1}")
        )
    rows = [navigation] if navigation else []
    rows.extend(
        [
            [InlineKeyboardButton(text="🛍 Новый заказ", callback_data="shop")],
            [InlineKeyboardButton(text="← Главное меню", callback_data="home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
