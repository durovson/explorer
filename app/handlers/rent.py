from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.core.enums import Currency, ProductType
from app.keyboards.menu import payment_keyboard, rent_confirm_keyboard, rent_keyboard
from app.services.marketapp import MarketappService
from app.services.orders import OrderService
from app.services.pricing import PriceService
from app.utils.media import render_card

router = Router(name="rent")


@router.callback_query(F.data.startswith("rent:"))
async def rent_catalog(
    callback: CallbackQuery, state: FSMContext, marketapp: MarketappService
) -> None:
    page = max(0, int((callback.data or "rent:0").split(":", 1)[1]))
    try:
        offers, has_next = await marketapp.rental_gifts(page)
    except Exception as exc:
        await callback.answer(f"Каталог Marketapp недоступен: {str(exc)[:100]}", show_alert=True)
        return
    packed = [
        {
            "nft_address": item.nft_address,
            "title": item.title,
            "days": item.days,
            "price_gram": str(item.price_gram),
            "photo_url": item.photo_url,
            "raw": item.raw,
        }
        for item in offers
    ]
    await state.update_data(rent_page=page, rent_offers=packed, rent_selected=None)
    lines = [
        "<b>🎁 Аренда NFT-подарков</b>",
        "",
        "Оплата исполнения Marketapp — из settlement-кошелька в GRAM.",
        "Вы оплачиваете заказ TON после выбора NFT.",
        "",
    ]
    if not offers:
        lines.append("Сейчас доступных предложений нет.")
    for index, offer in enumerate(offers, 1):
        lines.append(
            f"<b>#{index} {escape(offer.title)}</b> · {offer.days} дн. · "
            f"{offer.price_gram} GRAM"
        )
    if callback.message:
        await render_card(
            callback.message,
            "\n".join(lines),
            rent_keyboard(page, len(offers), has_next),
            "rent",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rentpick:"))
async def rent_pick(
    callback: CallbackQuery, state: FSMContext, pricing: PriceService
) -> None:
    data = await state.get_data()
    offers = data.get("rent_offers") or []
    try:
        index = int((callback.data or "rentpick:0").split(":", 1)[1])
        offer = offers[index]
        provider_price = Decimal(offer["price_gram"])
        total = pricing.calculate(
            ProductType.NFT_RENT,
            Currency.TON,
            provider_price_gram=provider_price,
        )
    except (IndexError, KeyError, ValueError):
        await callback.answer("Предложение устарело. Обновите каталог.", show_alert=True)
        return
    await state.update_data(rent_selected=offer)
    caption = (
        f"<b>🎁 {escape(offer['title'])}</b>\n\n"
        f"NFT: <code>{escape(offer['nft_address'])}</code>\n"
        f"Срок: <b>{offer['days']} дн.</b>\n"
        f"Цена Marketapp: <b>{provider_price} GRAM</b>\n"
        f"К оплате: <b>{total} TON</b>\n\n"
        "После blockchain-подтверждения платежа бот автоматически арендует NFT через Marketapp."
    )
    if callback.message:
        await render_card(
            callback.message,
            caption,
            rent_confirm_keyboard(),
            "rent",
            offer.get("photo_url"),
        )
    await callback.answer()


@router.callback_query(F.data == "rentconfirm")
async def rent_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    orders: OrderService,
    marketapp: MarketappService,
) -> None:
    if not callback.from_user.username:
        await callback.answer(
            "Для аренды установите Telegram username — он нужен для привязки заказа.",
            show_alert=True,
        )
        return
    data = await state.get_data()
    offer = data.get("rent_selected")
    if not offer:
        await callback.answer("Сначала выберите NFT из каталога.", show_alert=True)
        return
    try:
        marketapp.ensure_ready()
        order = await orders.create(
            user_id=callback.from_user.id,
            recipient=f"@{callback.from_user.username}",
            product=ProductType.NFT_RENT,
            currency=Currency.TON,
            nft_address=offer["nft_address"],
            rent_days=int(offer["days"]),
            provider_price_gram=Decimal(offer["price_gram"]),
            provider_payload=offer.get("raw") or {},
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except Exception as exc:
        await callback.answer(f"Не удалось создать аренду: {str(exc)[:120]}", show_alert=True)
        return
    await state.clear()
    minutes = max(
        1, int((order.expires_at - datetime.now(UTC)).total_seconds() / 60) + 1
    )
    caption = (
        "<b>🎁 Оплата аренды NFT</b>\n\n"
        f"NFT: <code>{escape(order.nft_address or '')}</code>\n"
        f"Срок: <b>{order.rent_days} дн.</b>\n"
        f"К оплате: <b>{order.amount} TON</b>\n\n"
        f"Адрес:\n<code>{order.wallet_address}</code>\n\n"
        f"Memo:\n<code>{order.memo}</code>\n\n"
        "⚠️ <b>Memo обязателен.</b>\n"
        f"Время на оплату: <b>{minutes} мин.</b>\n"
        f"Заказ: <code>{order.id}</code>"
    )
    if callback.message:
        await render_card(
            callback.message,
            caption,
            payment_keyboard(orders.payment_link(order), str(order.id)),
            "payment_wait",
            offer.get("photo_url"),
        )
    await callback.answer()
