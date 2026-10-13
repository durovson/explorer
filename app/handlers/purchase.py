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
from app.keyboards.menu import (
    back_home,
    currency_keyboard,
    payment_keyboard,
    product_options,
    recipient_keyboard,
)
from app.services.fragment import FragmentService
from app.services.orders import OrderService
from app.services.pricing import PriceService
from app.states import PurchaseStates
from app.utils.emoji import premium
from app.utils.media import edit_card, render_card

router = Router(name="purchase")


def _product_title(product: ProductType) -> str:
    if product is ProductType.STARS:
        return f"{premium('star')} Купить Stars"
    return f"{premium('diamond')} Купить Premium"


async def _remember_card(state: FSMContext, message: Message | None) -> None:
    if message is None:
        return
    await state.update_data(
        card_chat_id=message.chat.id,
        card_message_id=message.message_id,
    )


@router.callback_query(F.data.startswith("buy:"))
async def choose_recipient(callback: CallbackQuery, state: FSMContext) -> None:
    product = ProductType((callback.data or "buy:STARS").split(":", 1)[1])
    await state.clear()
    await state.update_data(product=product.value)
    if callback.message:
        rendered = await render_card(
            callback.message,
            f"<b>{_product_title(product)}</b>\n\n"
            "<blockquote>Выберите, кому отправить покупку.</blockquote>",
            recipient_keyboard(callback.from_user.username),
            "recipient",
        )
        await _remember_card(state, rendered)
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
        rendered = await render_card(
            callback.message,
            f"<b>{premium('users')} Получатель</b>\n\n"
            "Введите @username получателя:\n"
            "<blockquote>Например: <code>@username</code></blockquote>",
            back_home(),
            "recipient",
        )
        await _remember_card(state, rendered)
    await callback.answer()


@router.message(PurchaseStates.recipient)
async def recipient_input(
    message: Message, state: FSMContext, orders: OrderService, bot: Bot
) -> None:
    try:
        recipient = orders.normalize_recipient(message.text or "")
    except ValueError as exc:
        await message.answer(f"{premium('cancel')} {escape(str(exc))}")
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
        f"<b>Получатель:</b> {escape(data['recipient'])}\n\n"
        f"<blockquote>Выберите {'количество Stars' if product is ProductType.STARS else 'срок подписки'}.</blockquote>"
    )
    if message:
        rendered = await render_card(message, text, product_options(product.value), "product")
        await _remember_card(state, rendered)


async def _show_options_stored(bot: Bot, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    product = ProductType(data["product"])
    text = (
        f"<b>{_product_title(product)}</b>\n\n"
        f"<b>Получатель:</b> {escape(data['recipient'])}\n\n"
        f"<blockquote>Выберите {'количество Stars' if product is ProductType.STARS else 'срок подписки'}.</blockquote>"
    )
    rendered = await edit_card(
        bot,
        data["card_chat_id"],
        data["card_message_id"],
        text,
        product_options(product.value),
        "product",
    )
    await _remember_card(state, rendered)


@router.callback_query(F.data == "options")
async def options(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_options(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "amount:custom")
async def custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PurchaseStates.custom_stars)
    if callback.message:
        rendered = await render_card(
            callback.message,
            f"<b>{premium('edit')} Своё количество</b>\n\n"
            "Введите целое число от <b>50</b> до <b>1 000 000</b>.",
            back_home(),
            "product",
        )
        await _remember_card(state, rendered)
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
        await message.answer(
            f"{premium('cancel')} Введите целое число от 50 до 1 000 000."
        )
        return
    await state.update_data(stars_amount=amount, premium_months=None)
    with suppress(TelegramBadRequest):
        await message.delete()
    await _show_currencies_stored(bot, state, pricing)


@router.callback_query(F.data.startswith("amount:") | F.data.startswith("months:"))
async def select_option(
    callback: CallbackQuery, state: FSMContext, pricing: PriceService
) -> None:
    kind, raw = (callback.data or "").split(":", 1)
    if raw == "custom":
        return
    if kind == "amount":
        await state.update_data(stars_amount=int(raw), premium_months=None)
    else:
        await state.update_data(stars_amount=None, premium_months=int(raw))
    await _show_currencies(callback.message, state, pricing)
    await callback.answer()


async def _show_currencies(
    message: Message | None, state: FSMContext, pricing: PriceService
) -> None:
    await state.set_state(None)
    data = await state.get_data()
    try:
        text = await _currency_text(data, pricing)
    except Exception as exc:
        if message:
            rendered = await render_card(
                message,
                f"<b>{premium('warning')} Цена временно недоступна</b>\n\n"
                f"<blockquote>{escape(str(exc)[:180])}</blockquote>",
                back_home(),
                "error",
            )
            await _remember_card(state, rendered)
        return
    if message:
        rendered = await render_card(message, text, currency_keyboard(), "payment_method")
        await _remember_card(state, rendered)


async def _show_currencies_stored(
    bot: Bot, state: FSMContext, pricing: PriceService
) -> None:
    data = await state.get_data()
    await state.set_state(None)
    try:
        text = await _currency_text(data, pricing)
    except Exception as exc:
        rendered = await edit_card(
            bot,
            data["card_chat_id"],
            data["card_message_id"],
            f"<b>{premium('warning')} Цена временно недоступна</b>\n\n"
            f"<blockquote>{escape(str(exc)[:180])}</blockquote>",
            back_home(),
            "error",
        )
        await _remember_card(state, rendered)
        return
    rendered = await edit_card(
        bot,
        data["card_chat_id"],
        data["card_message_id"],
        text,
        currency_keyboard(),
        "payment_method",
    )
    await _remember_card(state, rendered)


async def _currency_text(data: dict, pricing: PriceService) -> str:
    product = ProductType(data["product"])
    kwargs = {
        "stars_amount": data.get("stars_amount"),
        "premium_months": data.get("premium_months"),
    }
    ton = await pricing.calculate(product, Currency.TON, **kwargs)
    label = (
        f"{data['stars_amount']} Stars"
        if product is ProductType.STARS
        else f"Telegram Premium — {data['premium_months']} мес."
    )
    return (
        f"{premium('payment')} <b>Оплата</b>\n\n"
        "<b>Детали:</b>\n"
        "<blockquote>"
        f"• <b>Товар:</b> {label}\n"
        f"• <b>Получатель:</b> {escape(data['recipient'])}\n"
        f"• <b>К оплате:</b> {ton} TON"
        "</blockquote>\n\n"
        f"{premium('info')} Итог уже включает сервисную комиссию и округление вверх."
    )


@router.callback_query(F.data.startswith("currency:"))
async def create_order(
    callback: CallbackQuery,
    state: FSMContext,
    orders: OrderService,
    fragment: FragmentService,
) -> None:
    if (callback.data or "") != "currency:TON":
        await callback.answer("Сейчас доступна оплата только TON", show_alert=True)
        return
    data = await state.get_data()
    product = ProductType(data["product"])
    try:
        await fragment.user_info(data["recipient"], product)
    except Exception as exc:
        await callback.answer(
            f"Не удалось проверить получателя: {str(exc)[:100]}", show_alert=True
        )
        return
    try:
        order = await orders.create(
            user_id=callback.from_user.id,
            recipient=data["recipient"],
            product=product,
            currency=Currency.TON,
            stars_amount=data.get("stars_amount"),
            premium_months=data.get("premium_months"),
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except Exception as exc:
        await callback.answer(
            f"Не удалось создать заказ: {str(exc)[:100]}", show_alert=True
        )
        return
    await state.clear()
    minutes = max(
        1, int((order.expires_at - datetime.now(UTC)).total_seconds() / 60) + 1
    )
    caption = (
        f"{premium('payment')} <b>Оплата заказа</b>\n\n"
        "<b>Детали:</b>\n"
        "<blockquote>"
        f"• <b>Товар:</b> {escape(order.item_label)}\n"
        f"• <b>Получатель:</b> {escape(order.recipient)}\n"
        f"• <b>Сумма:</b> {order.amount} TON"
        "</blockquote>\n\n"
        "<b>Адрес:</b>\n"
        f"<code>{order.wallet_address}</code>\n\n"
        f"{premium('message')} <b>Memo:</b>\n"
        f"<blockquote><code>{escape(order.memo)}</code></blockquote>\n"
        f"{premium('warning')} <b>Важно:</b> отправьте точную сумму и Memo без изменений.\n\n"
        f"Оплата действует <b>{minutes} мин.</b> · Заказ <code>#{str(order.id)[:10]}</code>"
    )
    rendered = await render_card(
        callback.message,
        caption,
        payment_keyboard(orders.payment_link(order), str(order.id)),
        "payment_wait",
    )
    if (
        rendered.chat.id != order.bot_chat_id
        or rendered.message_id != order.bot_message_id
    ):
        await orders.bind_message(order.id, rendered.chat.id, rendered.message_id)
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
            f"{premium('cancel')} <b>Заказ отменён</b>\n\n"
            f"<blockquote><code>#{str(order.id)[:10]}</code></blockquote>",
            back_home(),
            "error",
        )
    await callback.answer()
