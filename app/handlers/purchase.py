from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.enums import Currency, ProductType
from app.keyboards.menu import (
    back_home, back_to_options, currency_keyboard, payment_keyboard,
    product_options, recipient_keyboard,
)
from app.services.fragment import FragmentService
from app.services.orders import OrderService
from app.services.pricing import PriceService
from app.states import PurchaseStates
from app.utils.emoji import BACK, premium
from app.utils.i18n import tr
from app.utils.media import edit_card, render_card

router = Router(name="purchase")


def _price(value: Decimal, decimals: int = 9) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".") or "0"


def _title(product: ProductType) -> str:
    icon = premium("star" if product is ProductType.STARS else "diamond")
    return icon + " <b>" + (
        tr("Купить Stars", "Buy Stars")
        if product is ProductType.STARS else tr("Купить Premium", "Buy Premium")
    ) + "</b>"


def _back_recipient(product: ProductType) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=tr("Назад", "Back"),
            icon_custom_emoji_id=BACK,
            callback_data=f"buy:{product.value}",
        )]
    ])


async def _remember(state: FSMContext, message: Message | None) -> None:
    if message:
        await state.update_data(card_chat_id=message.chat.id, card_message_id=message.message_id)


async def _display_stored(
    bot: Bot, state: FSMContext, text: str, keyboard: InlineKeyboardMarkup, screen: str,
) -> None:
    data = await state.get_data()
    chat_id, message_id = data.get("card_chat_id"), data.get("card_message_id")
    if chat_id and message_id:
        edited = await edit_card(bot, chat_id, message_id, text, keyboard, screen)
        await _remember(state, edited)


@router.callback_query(F.data.startswith("buy:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        product = ProductType((callback.data or "buy:STARS").split(":", 1)[1])
    except ValueError:
        await callback.answer(tr("Товар недоступен", "Product unavailable"), show_alert=True)
        return
    await state.clear()
    await state.update_data(product=product.value)
    if callback.message:
        rendered = await render_card(
            callback.message,
            _title(product) + "\n\n<blockquote>" +
            tr("Кому отправить покупку?", "Who should receive the purchase?") + "</blockquote>",
            recipient_keyboard(callback.from_user.username),
            "recipient",
        )
        await _remember(state, rendered)
    await callback.answer()


@router.callback_query(F.data == "recipient:self")
async def recipient_self(callback: CallbackQuery, state: FSMContext, pricing: PriceService) -> None:
    if not callback.from_user.username:
        await callback.answer(tr("Установите username в Telegram", "Set a Telegram username first"), show_alert=True)
        return
    await state.update_data(recipient=f"@{callback.from_user.username}")
    await _show_options(callback.message, state, pricing)
    await callback.answer()


@router.callback_query(F.data == "recipient:other")
async def recipient_other(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.recipient)
    data = await state.get_data()
    product = ProductType(data["product"])
    if callback.message:
        rendered = await render_card(
            callback.message,
            _title(product) + " — " + tr("Другу", "Someone else") + "\n\n" +
            tr("Введите username получателя:", "Enter recipient username:") +
            "\n<blockquote><code>@username</code></blockquote>",
            _back_recipient(product), "recipient",
        )
        await _remember(state, rendered)
    await callback.answer()


@router.message(PurchaseStates.recipient)
async def recipient_input(message: Message, state: FSMContext, orders: OrderService, bot: Bot, pricing: PriceService) -> None:
    try:
        recipient = orders.normalize_recipient(message.text or "")
    except ValueError:
        data = await state.get_data()
        product = ProductType(data["product"])
        await _display_stored(
            bot, state,
            _title(product) + "\n\n" +
            tr("Неверный username. Попробуйте ещё раз:", "Invalid username. Please try again:") +
            "\n<blockquote><code>@username</code></blockquote>",
            _back_recipient(product), "recipient",
        )
        with suppress(TelegramBadRequest):
            await message.delete()
        return
    await state.update_data(recipient=recipient)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_options_stored(bot, state, pricing)


async def _option_prices(pricing: PriceService, product: ProductType) -> dict[int, str]:
    if product is not ProductType.STARS:
        return {}
    amounts = (50, 100, 250, 500, 1000, 2500)
    async def quote(quantity: int):
        try:
            return quantity, _price(await pricing.calculate(
                ProductType.STARS, Currency.TON, stars_amount=quantity
            ))
        except Exception:
            return quantity, None
    try:
        values = await asyncio.wait_for(
            asyncio.gather(*(quote(q) for q in amounts)), timeout=3.0
        )
    except TimeoutError:
        return {}
    return {quantity: value for quantity, value in values if value is not None}


async def _options_content(state: FSMContext, pricing: PriceService) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    product = ProductType(data["product"])
    text = (
        _title(product) + "\n\n<blockquote>" +
        tr("Получатель: ", "Recipient: ") + escape(data["recipient"]) +
        "</blockquote>\n\n" +
        tr(
            "Выберите количество звёзд:" if product is ProductType.STARS else "Выберите срок подписки:",
            "Choose the number of Stars:" if product is ProductType.STARS else "Choose subscription duration:",
        )
    )
    return text, product_options(product.value, await _option_prices(pricing, product))


async def _show_options(message: Message | None, state: FSMContext, pricing: PriceService) -> None:
    await state.set_state(None)
    text, keyboard = await _options_content(state, pricing)
    if message:
        await _remember(state, await render_card(message, text, keyboard, "product"))


async def _show_options_stored(bot: Bot, state: FSMContext, pricing: PriceService) -> None:
    await state.set_state(None)
    text, keyboard = await _options_content(state, pricing)
    await _display_stored(bot, state, text, keyboard, "product")


@router.callback_query(F.data == "options")
async def options(callback: CallbackQuery, state: FSMContext, pricing: PriceService) -> None:
    await _show_options(callback.message, state, pricing)
    await callback.answer()


@router.callback_query(F.data == "amount:custom")
async def custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.custom_stars)
    if callback.message:
        await _remember(state, await render_card(
            callback.message,
            f"{premium('edit')} <b>" + tr("Своё количество", "Custom amount") + "</b>\n\n" +
            tr("Введите число звёзд от 50 до 10000:", "Enter a Stars quantity from 50 to 10000:"),
            back_to_options(), "product",
        ))
    await callback.answer()


@router.message(PurchaseStates.custom_stars)
async def custom_amount_input(message: Message, state: FSMContext, bot: Bot, pricing: PriceService) -> None:
    try:
        amount = int(message.text or "")
        if not 50 <= amount <= 10000:
            raise ValueError
    except ValueError:
        await _display_stored(
            bot, state,
            f"{premium('warning')} " + tr("Введите целое число от 50 до 10000.", "Enter a whole number between 50 and 10000."),
            back_to_options(), "product",
        )
        with suppress(TelegramBadRequest):
            await message.delete()
        return
    await state.update_data(stars_amount=amount, premium_months=None)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_payment_stored(bot, state, pricing)


@router.callback_query(F.data.startswith("amount:") | F.data.startswith("months:"))
async def select_option(callback: CallbackQuery, state: FSMContext, pricing: PriceService) -> None:
    kind, raw = (callback.data or "").split(":", 1)
    if raw == "custom":
        return
    if kind == "amount":
        await state.update_data(stars_amount=int(raw), premium_months=None)
    else:
        await state.update_data(stars_amount=None, premium_months=int(raw))
    await _show_payment(callback.message, state, pricing)
    await callback.answer()


async def _payment_content(data: dict, pricing: PriceService) -> str:
    product = ProductType(data["product"])
    quote = await pricing.calculate(
        product, Currency.TON,
        stars_amount=data.get("stars_amount"),
        premium_months=data.get("premium_months"),
    )
    label = (
        f"{data['stars_amount']} Stars"
        if product is ProductType.STARS
        else f"Telegram Premium · {data['premium_months']} " + tr("мес.", "months")
    )
    return (
        f"{premium('payment')} <b>" + tr("Оплата", "Payment") + "</b>\n\n"
        + tr("<b>Детали:</b>", "<b>Details:</b>") + "\n<blockquote>"
        + "• " + escape(label) + "\n"
        + "• " + tr("Получатель: ", "Recipient: ") + escape(data["recipient"]) + "\n"
        + "• " + tr("К оплате: ", "Total: ") + f"<b>{_price(quote)} GRAM</b></blockquote>\n"
        + f"{premium('info')} " +
        tr("Итог уже включает сервисную комиссию.", "Service fee is included in the total.")
    )


async def _show_payment(message: Message | None, state: FSMContext, pricing: PriceService) -> None:
    await state.set_state(None)
    try:
        text = await _payment_content(await state.get_data(), pricing)
        keyboard = currency_keyboard()
    except Exception:
        text = f"{premium('warning')} " + tr("Цена временно недоступна. Попробуйте снова.", "Price temporarily unavailable. Try again.")
        keyboard = back_to_options()
    if message:
        await _remember(state, await render_card(message, text, keyboard, "payment_method"))


async def _show_payment_stored(bot: Bot, state: FSMContext, pricing: PriceService) -> None:
    await state.set_state(None)
    try:
        text = await _payment_content(await state.get_data(), pricing)
        keyboard = currency_keyboard()
    except Exception:
        text = f"{premium('warning')} " + tr("Цена временно недоступна. Попробуйте снова.", "Price temporarily unavailable. Try again.")
        keyboard = back_to_options()
    await _display_stored(bot, state, text, keyboard, "payment_method")


@router.callback_query(F.data.startswith("currency:"))
async def create_order(
    callback: CallbackQuery, state: FSMContext, orders: OrderService, fragment: FragmentService,
) -> None:
    if (callback.data or "") != "currency:TON":
        await callback.answer(tr("Доступна только оплата TON", "Only TON payments are available"), show_alert=True)
        return
    data = await state.get_data()
    try:
        product = ProductType(data["product"])
        recipient = data["recipient"]
    except (ValueError, KeyError):
        await callback.answer(tr("Откройте покупку заново", "Restart the purchase flow"), show_alert=True)
        return
    # Acknowledge immediately: recipient preflight and persistence may take seconds.
    await callback.answer()
    try:
        await fragment.user_info(recipient, product)
    except Exception:
        if callback.message:
            await render_card(
                callback.message,
                f"{premium('warning')} " + tr(
                    "Получатель не может получить этот товар. Проверьте username.",
                    "This recipient cannot receive this product. Check the username.",
                ),
                back_to_options(), "error",
            )
        return
    try:
        order = await orders.create(
            user_id=callback.from_user.id,
            recipient=recipient,
            product=product,
            currency=Currency.TON,
            stars_amount=data.get("stars_amount"),
            premium_months=data.get("premium_months"),
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except Exception:
        if callback.message:
            await render_card(
                callback.message,
                f"{premium('warning')} " + tr(
                    "Не удалось создать заказ. Попробуйте ещё раз.",
                    "Could not create the order. Please retry.",
                ),
                back_to_options(), "error",
            )
        return
    await state.clear()
    minutes = max(1, int((order.expires_at - datetime.now(UTC)).total_seconds() / 60) + 1)
    label = (
        f"{order.stars_amount} Stars"
        if order.stars_amount is not None
        else f"Telegram Premium · {order.premium_months} " + tr("мес.", "months")
    )
    caption = (
        f"{premium('payment')} <b>" + tr("Оплата — GRAM", "Payment — GRAM") + "</b>\n\n"
        + tr("<b>Детали:</b>", "<b>Details:</b>") + "\n<blockquote>"
        + "• " + escape(label) + "\n"
        + "• " + tr("Получатель: ", "Recipient: ") + escape(order.recipient)
        + "</blockquote>\n\n"
        + tr("Отправьте ", "Send ") + f"<b>{_price(order.amount)} GRAM</b> "
        + tr("на адрес:", "to this address:") + "\n"
        + f"<code>{escape(order.wallet_address)}</code>\n\n"
        + f"{premium('message')} <b>Memo:</b>\n<blockquote><code>{escape(order.memo)}</code></blockquote>\n"
        + f"{premium('warning')} " + tr(
            "<b>Обязательно укажите Memo! Без него оплата не будет найдена.</b>",
            "<b>You must include the Memo! Without it, your payment cannot be identified.</b>",
        )
        + "\n\n" + f"{premium('calendar')} " +
        tr("Время на оплату: ", "Payment window: ") + f"<b>{minutes} "
        + tr("минут", "minutes") + "</b>"
    )
    rendered = await render_card(
        callback.message, caption,
        payment_keyboard(orders.payment_link(order), str(order.id)), "payment_wait",
    )
    if rendered.chat.id != order.bot_chat_id or rendered.message_id != order.bot_message_id:
        await orders.bind_message(order.id, rendered.chat.id, rendered.message_id)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel(callback: CallbackQuery, orders: OrderService) -> None:
    try:
        order = await orders.cancel(UUID((callback.data or "").split(":", 1)[1]), callback.from_user.id)
    except Exception:
        await callback.answer(tr("Нельзя отменить уже оплаченный или закрытый заказ", "A paid or closed order cannot be cancelled"), show_alert=True)
        return
    if callback.message:
        await render_card(
            callback.message,
            f"{premium('cancel')} <b>" + tr("Заказ отменён", "Order cancelled") +
            f"</b>\n<blockquote><code>#{str(order.id)[:8]}</code></blockquote>",
            back_home(), "error",
        )
    await callback.answer()
