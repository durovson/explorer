from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from app.config import Settings
from app.core.enums import Currency, OrderStatus, ProductType
from app.models.entities import Order
from app.repositories.orders import OrderRepository
from app.services.pricing import PriceService

USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{3,32}$")


class OrderService:
    def __init__(self, settings: Settings, orders: OrderRepository, pricing: PriceService):
        self.settings = settings
        self.orders = orders
        self.pricing = pricing

    @staticmethod
    def normalize_recipient(raw: str) -> str:
        value = raw.strip()
        if not value.startswith("@"):
            value = "@" + value
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("Введите корректный @username получателя")
        return value

    @staticmethod
    def _memo(order_id: UUID) -> str:
        token = order_id.hex[:12].upper()
        return f"STRS.TG/{token[:4]}-{token[4:8]}-{token[8:12]}"

    async def create(
        self,
        *,
        user_id: int,
        recipient: str,
        product: ProductType,
        currency: Currency,
        stars_amount: int | None,
        premium_months: int | None,
        chat_id: int,
        message_id: int,
    ) -> Order:
        if currency is not Currency.TON:
            raise ValueError("Сейчас доступна оплата только TON")
        recipient = self.normalize_recipient(recipient)
        price_kwargs = {
            "stars_amount": stars_amount,
            "premium_months": premium_months,
        }
        ton_quote = await self.pricing.quote(product, Currency.TON, **price_kwargs)
        usd_equivalent = await self.pricing.calculate(
            product, Currency.USDT, **price_kwargs
        )
        order_id = uuid4()
        values = {
            "id": str(order_id),
            "user_id": user_id,
            "recipient": recipient,
            "product_type": product.value,
            "stars_amount": stars_amount,
            "premium_months": premium_months,
            "currency": Currency.TON.value,
            "amount": str(ton_quote.total),
            "usd_equivalent": str(usd_equivalent),
            "provider_cost_ton": str(ton_quote.base),
            "wallet_address": self.settings.TON_RECEIVER_ADDRESS,
            "memo": self._memo(order_id),
            "status": OrderStatus.WAITING_PAYMENT.value,
            "expires_at": (
                datetime.now(UTC)
                + timedelta(minutes=self.settings.PAYMENT_TTL_MINUTES)
            ).isoformat(),
            "bot_chat_id": chat_id,
            "bot_message_id": message_id,
        }
        return await self.orders.create(values)

    async def cancel(self, order_id: UUID, user_id: int) -> Order:
        order = await self.orders.cancel(order_id, user_id)
        if order is None:
            raise ValueError("Заказ уже оплачен, отменён или не найден")
        return order

    def payment_link(self, order: Order) -> str:
        decimals = 9 if order.currency is Currency.TON else 6
        params: dict[str, str | int] = {
            "amount": int(order.amount * (10**decimals)),
            "text": order.memo,
            "exp": int(order.expires_at.timestamp()),
        }
        if order.currency is Currency.USDT:
            params["jetton"] = self.settings.USDT_MASTER_ADDRESS
        return f"ton://transfer/{order.wallet_address}?{urlencode(params)}"
