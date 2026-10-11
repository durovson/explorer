from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import Currency, FulfillmentAttemptStatus, OrderStatus, ProductType


class User(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    referrer_id: int | None = None
    created_at: datetime | None = None


class Order(BaseModel):
    id: UUID
    user_id: int
    recipient: str
    product_type: ProductType
    stars_amount: int | None = None
    premium_months: int | None = None
    currency: Currency
    amount: Decimal
    wallet_address: str
    memo: str
    status: OrderStatus
    expires_at: datetime
    created_at: datetime
    updated_at: datetime | None = None
    paid_at: datetime | None = None
    completed_at: datetime | None = None
    tx_hash: str | None = None
    tx_lt: int | None = None
    sender_address: str | None = None
    fragment_order_id: str | None = None
    fragment_response: dict[str, Any] | None = None
    error: str | None = None
    processing_lease_until: datetime | None = None
    bot_chat_id: int | None = None
    bot_message_id: int | None = None

    @property
    def item_label(self) -> str:
        if self.product_type is ProductType.STARS:
            return f"{self.stars_amount} ⭐"
        return f"Telegram Premium — {self.premium_months} мес."


class FulfillmentAttempt(BaseModel):
    id: int
    order_id: UUID
    idempotency_key: str
    status: FulfillmentAttemptStatus
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None = None
    http_status: int | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReferralStats(BaseModel):
    invited: int = 0
    paid_orders: int = 0
    paid_ton: Decimal = Decimal("0")
    paid_usdt: Decimal = Decimal("0")


class AdminStats(BaseModel):
    users: int = 0
    orders: int = 0
    waiting: int = 0
    completed: int = 0
    manual_review: int = 0
    volume_ton: Decimal = Decimal("0")
    volume_usdt: Decimal = Decimal("0")
