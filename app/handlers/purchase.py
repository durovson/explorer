from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.core.enums import Currency, ProductType
from app.keyboards.menu import (
    back_home,
    currency_keyboard,
    payment_keyboard,
    product_options,
    recipient_keyboard,
)
from app.services.marketapp import MarketappService
from app.services.orders import OrderService
from app.services.pricing import PriceService
from app.states import PurchaseStates
from app.utils.media import edit_card, render_card

router = Router(name="purchase")


def _product_title(product: ProductType) -> str:
    if product is ProductType.STARS:
        return "⭐ Купить Stars"
    if product is ProductType.PREMIUM:
        return "💎 Купить Premium"
    return "◈ Пополнить GRAM"


def _option_word(product: ProductType) -> str:
    if product is ProductType.STARS:
        return "количество Stars"
    if product is ProductType.PREMIUM:
        return "срок подписки"
    return "сумму GRAM"


@router.callback_query(F.data.startswith("buy:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext) -> None:
    product = ProductType((callback.data or "buy:STARS").split(":", 1)[1])
    if product is ProductType.NFT_RENT:
        await callback.answer()
        return
    await state.clear()
    await state.update_data(
        product=product.value,
        card_chat_id=callback.message.chat.id if callback.message else None,
        card_message_id=callback.message.message_id if callback.message else None,
    )
    text = f"<b>{_product_title(product)}</b>\n\nКому отправить покупку?"
    if callback.message:
        await render_card(
            callback.message,
            text,
            recipient_keyboard(callback.from_user.username),
            "recipient",
        )
    await callback.answer()


@router.callback_query(F.data == "recipient:self")
async def recipient_self(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user.username:
        await callback.answer("Сначала установите username в Telegram", show_alert=True)
        return
    await state.update_data(recipient=f"@{callback.from_user.username}")
    await _show_options(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "recipient:other")
async def recipient_other(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.recipient)
    if callback.message:
        await render_card(
            callback.message,
            "<b>🎁 Получатель</b>\n\nВведите @username получателя:",
            back_home(),
            "recipient",
        )
    await callback.answer()


@router.message(PurchaseStates.recipient)
async def recipient_input(
    message: Message, state: FSMContext, orders: OrderService, bot: Bot
) -> None:
    try:
        recipient = orders.normalize_recipient(message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {escape(str(exc))}")
        return
    await state.update_data(recipient=recipient)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_options_stored(bot, state)


async def _show_options(message: Message | None, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    product = ProductType(data["product"])
    text = (
        f"<b>{_product_title(product)}</b>\n\n"
        f"Получатель: <b>{escape(data['recipient'])}</b>\n\n"
        f"Выберите {_option_word(product)}:"
    )
    if message:
        await render_card(message, text, product_options(product.value), "product")


async def _show_options_stored(bot: Bot, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    product = ProductType(data["product"])
    text = (
        f"<b>{_product_title(product)}</b>\n\n"
        f"Получатель: <b>{escape(data['recipient'])}</b>\n\n"
        f"Выберите {_option_word(product)}:"
    )
    await edit_card(
        bot,
        data["card_chat_id"],
        data["card_message_id"],
        text,
        product_options(product.value),
        "product",
    )


@router.callback_query(F.data == "options")
async def options(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_options(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "amount:custom")
async def custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.custom_stars)
    if callback.message:
        await render_card(
            callback.message,
            "<b>⭐ Своё количество</b>\n\nВведите целое число от 50 до 1 000 000:",
            back_home(),
            "product",
        )
    await callback.answer()


@router.message(PurchaseStates.custom_stars)
async def custom_amount_input(
    message: Message, state: FSMContext, bot: Bot, pricing: PriceService
) -> None:
    try:
        amount = int(message.text or "")
        if not 50 <= amount <= 1_000_000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 50 до 1 000 000.")
        return
    await state.update_data(stars_amount=amount, premium_months=None, gram_amount=None)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_currencies_stored(bot, state, pricing)


@router.callback_query(F.data == "gram:custom")
async def custom_gram(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.custom_gram)
    if callback.message:
        await render_card(
            callback.message,
            "<b>◈ Сумма GRAM</b>\n\nВведите сумму, например <code>5</code> или <code>12.5</code>:",
            back_home(),
            "product",
        )
    await callback.answer()


@router.message(PurchaseStates.custom_gram)
async def custom_gram_input(
    message: Message, state: FSMContext, bot: Bot, pricing: PriceService
) -> None:
    try:
        amount = Decimal((message.text or "").replace(",", ".").strip())
        if amount <= 0:
            raise ValueError
        pricing.calculate(ProductType.GRAM, Currency.TON, gram_amount=amount)
    except (InvalidOperation, ValueError):
        await message.answer("❌ Введите корректную сумму GRAM в допустимом диапазоне.")
        return
    await state.update_data(stars_amount=None, premium_months=None, gram_amount=str(amount))
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_currencies_stored(bot, state, pricing)


@router.callback_query(
    F.data.startswith("amount:") | F.data.startswith("months:") | F.data.startswith("gram:")
)
async def select_option(
    callback: CallbackQuery, state: FSMContext, pricing: PriceService
) -> None:
    kind, raw = (callback.data or "").split(":", 1)
    if raw == "custom":
        return
    if kind == "amount":
        await state.update_data(stars_amount=int(raw), premium_months=None, gram_amount=None)
    elif kind == "months":
        await state.update_data(stars_amount=None, premium_months=int(raw), gram_amount=None)
    else:
        await state.update_data(stars_amount=None, premium_months=None, gram_amount=raw)
    await _show_currencies(callback.message, state, pricing)
    await callback.answer()


async def _show_currencies(
    message: Message | None, state: FSMContext, pricing: PriceService
) -> None:
    await state.set_state(None)
    data = await state.get_data()
    product = ProductType(data["product"])
    text = _currency_text(data, pricing)
    if message:
        await render_card(
            message,
            text,
            currency_keyboard(ton_only=product is ProductType.GRAM),
            "payment_method",
        )


async def _show_currencies_stored(
    bot: Bot, state: FSMContext, pricing: PriceService
) -> None:
    data = await state.get_data()
    product = ProductType(data["product"])
    text = _currency_text(data, pricing)
    await state.set_state(None)
    await edit_card(
        bot,
        data["card_chat_id"],
        data["card_message_id"],
        text,
        currency_keyboard(ton_only=product is ProductType.GRAM),
        "payment_method",
    )


def _currency_text(data: dict, pricing: PriceService) -> str:
    product = ProductType(data["product"])
    kwargs = {
        "stars_amount": data.get("stars_amount"),
        "premium_months": data.get("premium_months"),
        "gram_amount": Decimal(data["gram_amount"]) if data.get("gram_amount") else None,
    }
    if product is ProductType.STARS:
        label = f"{data['stars_amount']} ⭐"
    elif product is ProductType.PREMIUM:
        label = f"Telegram Premium — {data['premium_months']} мес."
    else:
        label = f"{data['gram_amount']} GRAM на баланс"
    ton = pricing.calculate(product, Currency.TON, **kwargs)
    lines = [
        f"<b>{label}</b>",
        f"Получатель: <b>{escape(data['recipient'])}</b>",
        "",
        "Выберите способ оплаты:",
        "",
        f"💎 TON: <b>{ton} TON</b>",
    ]
    if product is not ProductType.GRAM:
        usdt = pricing.calculate(product, Currency.USDT, **kwargs)
        lines.append(f"💵 USDT (TON): <b>{usdt} USDT</b>")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("currency:"))
async def create_order(
    callback: CallbackQuery,
    state: FSMContext,
    orders: OrderService,
    marketapp: MarketappService,
) -> None:
    data = await state.get_data()
    product = ProductType(data["product"])
    currency = Currency((callback.data or "currency:TON").split(":", 1)[1])
    try:
        marketapp.ensure_ready()
        preflight = await marketapp.search_recipient(product, data["recipient"])
        order = await orders.create(
            user_id=callback.from_user.id,
            recipient=data["recipient"],
            product=product,
            currency=currency,
            stars_amount=data.get("stars_amount"),
            premium_months=data.get("premium_months"),
            gram_amount=(Decimal(data["gram_amount"]) if data.get("gram_amount") else None),
            provider_payload=preflight,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except Exception as exc:
        await callback.answer(
            f"Marketapp не готов принять заказ: {str(exc)[:120]}",
            show_alert=True,
        )
        return
    await state.clear()
    minutes = max(
        1, int((order.expires_at - datetime.now(UTC)).total_seconds() / 60) + 1
    )
    caption = (
        f"<b>💎 Оплата — {order.currency.value}</b>\n\n"
        f"Товар: <b>{escape(order.item_label)}</b>\n"
        f"Получатель: <b>{escape(order.recipient)}</b>\n"
        f"Сумма: <b>{order.amount} {order.currency.value}</b>\n\n"
        f"Адрес:\n<code>{order.wallet_address}</code>\n\n"
        f"Memo (комментарий):\n<code>{order.memo}</code>\n\n"
        "⚠️ <b>Обязательно укажите memo.</b> Без него платеж не будет сопоставлен.\n\n"
        f"Время на оплату: <b>{minutes} мин.</b>\n"
        f"Заказ: <code>{order.id}</code>"
    )
    await render_card(
        callback.message,
        caption,
        payment_keyboard(orders.payment_link(order), str(order.id)),
        "payment_wait",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel(callback: CallbackQuery, orders: OrderService) -> None:
    try:
        order = await orders.cancel(
            UUID((callback.data or "").split(":", 1)[1]), callback.from_user.id
        )
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if callback.message:
        await render_card(
            callback.message,
            f"✕ <b>Заказ отменён</b>\n\n<code>{order.id}</code>",
            back_home(),
            "error",
        )
    await callback.answer()
