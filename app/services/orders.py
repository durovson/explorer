from __future__ import annotations

import re
import secrets
import string
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from app.config import Settings
from app.core.enums import Currency, OrderProvider, OrderStatus, ProductType
from app.models.entities import Order
from app.repositories.orders import OrderRepository
from app.services.pricing import PriceService

USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{3,32}$")


class OrderService:
    def __init__(
        self, settings: Settings, orders: OrderRepository, pricing: PriceService
    ):
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
    def _memo() -> str:
        alphabet = string.ascii_uppercase + string.digits
        return "SP-" + "".join(secrets.choice(alphabet) for _ in range(12))

    async def create(
        self,
        *,
        user_id: int,
        recipient: str,
        product: ProductType,
        currency: Currency,
        stars_amount: int | None = None,
        premium_months: int | None = None,
        gram_amount: Decimal | None = None,
        nft_address: str | None = None,
        rent_days: int | None = None,
        provider_price_gram: Decimal | None = None,
        provider_payload: dict[str, Any] | None = None,
        provider: OrderProvider = OrderProvider.MARKETAPP,
        chat_id: int,
        message_id: int,
    ) -> Order:
        recipient = self.normalize_recipient(recipient)
        amount = self.pricing.calculate(
            product,
            currency,
            stars_amount=stars_amount,
            premium_months=premium_months,
            gram_amount=gram_amount,
            provider_price_gram=provider_price_gram,
        )
        values = {
            "id": str(uuid4()),
            "user_id": user_id,
            "recipient": recipient,
            "product_type": product.value,
            "stars_amount": stars_amount,
            "premium_months": premium_months,
            "gram_amount": str(gram_amount) if gram_amount is not None else None,
            "nft_address": nft_address,
            "rent_days": rent_days,
            "provider_price_gram": (
                str(provider_price_gram) if provider_price_gram is not None else None
            ),
            "provider_payload": provider_payload or {},
            "provider": provider.value,
            "currency": currency.value,
            "amount": str(amount),
            "wallet_address": self.settings.TON_RECEIVER_ADDRESS,
            "memo": self._memo(),
            "status": OrderStatus.WAITING_PAYMENT.value,
            "expires_at": (
                datetime.now(UTC) + timedelta(minutes=self.settings.PAYMENT_TTL_MINUTES)
            ).isoformat(),
            "bot_chat_id": chat_id,
            "bot_message_id": message_id,
        }
        return await self.orders.create(values)

    async def cancel(self, order_id: UUID, user_id: int) -> Order:
        order = await self.orders.cancel(order_id, user_id)
        if order is None:
            raise ValueError("Заказ уже оплачен, отменен или не найден")
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
