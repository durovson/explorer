from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from html import escape
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.core.enums import Currency, ProductType
from app.keyboards.menu import back_home, currency_keyboard, payment_keyboard, product_options, recipient_keyboard
from app.services.fragment import FragmentService
from app.services.orders import OrderService
from app.services.pricing import PriceService
from app.states import PurchaseStates
from app.utils.media import edit_card, render_card

router = Router(name="purchase")


@router.callback_query(F.data.startswith("buy:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext) -> None:
    product = ProductType((callback.data or "buy:STARS").split(":", 1)[1])
    await state.clear()
    await state.update_data(product=product.value, card_chat_id=callback.message.chat.id if callback.message else None, card_message_id=callback.message.message_id if callback.message else None)
    title = "⭐ Купить Stars" if product is ProductType.STARS else "💎 Купить Premium"
    if callback.message:
        await render_card(callback.message, f"<b>{title}</b>\n\nКому отправить покупку?", recipient_keyboard(callback.from_user.username), "recipient")
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
        await render_card(callback.message, "<b>🎁 Получатель</b>\n\nВведите @username получателя:", back_home(), "recipient")
    await callback.answer()


@router.message(PurchaseStates.recipient)
async def recipient_input(message: Message, state: FSMContext, orders: OrderService, bot: Bot) -> None:
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
    title = "⭐ Купить Stars" if product is ProductType.STARS else "💎 Купить Premium"
    text = f"<b>{title}</b>\n\nПолучатель: <b>{escape(data['recipient'])}</b>\n\nВыберите {'количество' if product is ProductType.STARS else 'срок подписки'}:"
    if message:
        await render_card(message, text, product_options(product.value), "product")


async def _show_options_stored(bot: Bot, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    product = ProductType(data["product"])
    title = "⭐ Купить Stars" if product is ProductType.STARS else "💎 Купить Premium"
    text = f"<b>{title}</b>\n\nПолучатель: <b>{escape(data['recipient'])}</b>\n\nВыберите {'количество' if product is ProductType.STARS else 'срок подписки'}:"
    await edit_card(bot, data["card_chat_id"], data["card_message_id"], text, product_options(product.value), "product")


@router.callback_query(F.data == "options")
async def options(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_options(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "amount:custom")
async def custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.custom_stars)
    if callback.message:
        await render_card(callback.message, "<b>⭐ Своё количество</b>\n\nВведите целое число от 50 до 1 000 000:", back_home(), "product")
    await callback.answer()


@router.message(PurchaseStates.custom_stars)
async def custom_amount_input(message: Message, state: FSMContext, bot: Bot, pricing: PriceService) -> None:
    try:
        amount = int(message.text or "")
        if not 50 <= amount <= 1_000_000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 50 до 1 000 000.")
        return
    await state.update_data(stars_amount=amount, premium_months=None)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_currencies_stored(bot, state, pricing)


@router.callback_query(F.data.startswith("amount:") | F.data.startswith("months:"))
async def select_option(callback: CallbackQuery, state: FSMContext, pricing: PriceService) -> None:
    kind, raw = (callback.data or "").split(":", 1)
    if raw == "custom":
        return
    if kind == "amount":
        await state.update_data(stars_amount=int(raw), premium_months=None)
    else:
        await state.update_data(stars_amount=None, premium_months=int(raw))
    await _show_currencies(callback.message, state, pricing)
    await callback.answer()


async def _show_currencies(message: Message | None, state: FSMContext, pricing: PriceService) -> None:
    await state.set_state(None)
    data = await state.get_data()
    try:
        text = await _currency_text(data, pricing)
    except Exception as exc:
        if message:
            await render_card(message, f"<b>⚠️ Цена временно недоступна</b>\n\n{escape(str(exc)[:180])}", back_home(), "error")
        return
    if message:
        await render_card(message, text, currency_keyboard(), "payment_method")


async def _show_currencies_stored(bot: Bot, state: FSMContext, pricing: PriceService) -> None:
    data = await state.get_data()
    await state.set_state(None)
    try:
        text = await _currency_text(data, pricing)
    except Exception as exc:
        await edit_card(bot, data["card_chat_id"], data["card_message_id"], f"<b>⚠️ Цена временно недоступна</b>\n\n{escape(str(exc)[:180])}", back_home(), "error")
        return
    await edit_card(bot, data["card_chat_id"], data["card_message_id"], text, currency_keyboard(), "payment_method")


async def _currency_text(data: dict, pricing: PriceService) -> str:
    product = ProductType(data["product"])
    kwargs = {"stars_amount": data.get("stars_amount"), "premium_months": data.get("premium_months")}
    ton = await pricing.calculate(product, Currency.TON, **kwargs)
    usdt = await pricing.calculate(product, Currency.USDT, **kwargs)
    label = f"{data['stars_amount']} ⭐" if product is ProductType.STARS else f"Telegram Premium — {data['premium_months']} мес."
    return f"<b>{label}</b>\nПолучатель: <b>{escape(data['recipient'])}</b>\n\nВыберите способ оплаты:\n\n💎 TON: <b>{ton} TON</b>\n💵 USDT (TON): <b>{usdt} USDT</b>"


@router.callback_query(F.data.startswith("currency:"))
async def create_order(callback: CallbackQuery, state: FSMContext, orders: OrderService, fragment: FragmentService) -> None:
    data = await state.get_data()
    product = ProductType(data["product"])
    try:
        await fragment.user_info(data["recipient"], product)
    except Exception as exc:
        await callback.answer(f"Получатель не прошёл проверку Marketapp: {str(exc)[:100]}", show_alert=True)
        return
    try:
        order = await orders.create(user_id=callback.from_user.id, recipient=data["recipient"], product=product, currency=Currency((callback.data or "currency:TON").split(":", 1)[1]), stars_amount=data.get("stars_amount"), premium_months=data.get("premium_months"), chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception as exc:
        await callback.answer(f"Не удалось зафиксировать цену Marketapp: {str(exc)[:100]}", show_alert=True)
        return
    await state.clear()
    minutes = max(1, int((order.expires_at - datetime.now(UTC)).total_seconds() / 60) + 1)
    caption = f"<b>💎 Оплата — {order.currency.value}</b>\n\nТовар: <b>{escape(order.item_label)}</b>\nПолучатель: <b>{escape(order.recipient)}</b>\nСумма: <b>{order.amount} {order.currency.value}</b>\n\nАдрес:\n<code>{order.wallet_address}</code>\n\nMemo (комментарий):\n<code>{order.memo}</code>\n\n⚠️ <b>Обязательно укажите memo.</b> Без него платеж не будет сопоставлен.\n\nВремя на оплату: <b>{minutes} мин.</b>\nЗаказ: <code>{order.id}</code>"
    await render_card(callback.message, caption, payment_keyboard(orders.payment_link(order), str(order.id)), "payment_wait")
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel(callback: CallbackQuery, orders: OrderService) -> None:
    try:
        order = await orders.cancel(UUID((callback.data or "").split(":", 1)[1]), callback.from_user.id)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if callback.message:
        await render_card(callback.message, f"✕ <b>Заказ отменён</b>\n\n<code>{order.id}</code>", back_home(), "error")
    await callback.answer()
