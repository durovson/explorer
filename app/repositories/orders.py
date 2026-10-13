from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.enums import Currency, FulfillmentAttemptStatus, OrderStatus
from app.core.exceptions import ConcurrentUpdateError
from app.database import SupabaseDatabase
from app.models.entities import FulfillmentAttempt, Order, ShopStats


class OrderRepository:
    def __init__(self, database: SupabaseDatabase):
        self._db = database

    @staticmethod
    def _order(data: dict[str, Any]) -> Order:
        return Order.model_validate(data)

    async def create(self, values: dict[str, Any]) -> Order:
        response = await self._db.run(
            lambda client: client.table("orders").insert(values).execute()
        )
        return self._order(response.data[0])

    async def update_bot_message(
        self, order_id: UUID, chat_id: int, message_id: int
    ) -> Order | None:
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .update(
                    {
                        "bot_chat_id": chat_id,
                        "bot_message_id": message_id,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
                .eq("id", str(order_id))
                .execute()
            )
        )
        return self._order(response.data[0]) if response.data else None

    async def shop_stats(self) -> ShopStats:
        response = await self._db.rpc("shop_public_stats", {})
        return ShopStats.model_validate(response.data[0] if response.data else {})

    async def get(self, order_id: UUID) -> Order | None:
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .select("*")
                .eq("id", str(order_id))
                .limit(1)
                .execute()
            )
        )
        return self._order(response.data[0]) if response.data else None

    async def get_for_user(self, order_id: UUID, user_id: int) -> Order | None:
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .select("*")
                .eq("id", str(order_id))
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        )
        return self._order(response.data[0]) if response.data else None

    async def list_for_user(
        self, user_id: int, page: int, page_size: int = 5
    ) -> tuple[list[Order], bool]:
        start = max(0, page) * page_size
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .range(start, start + page_size)
                .execute()
            )
        )
        rows = response.data or []
        return [self._order(row) for row in rows[:page_size]], len(rows) > page_size

    async def list_open(self, currency: Currency, limit: int) -> list[Order]:
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .select("*")
                .eq("status", OrderStatus.WAITING_PAYMENT.value)
                .eq("currency", currency.value)
                .gt("expires_at", datetime.now(UTC).isoformat())
                .order("created_at")
                .limit(limit)
                .execute()
            )
        )
        return [self._order(row) for row in response.data or []]

    async def list_ready_for_fulfillment(self, limit: int) -> list[Order]:
        response = await self._db.run(
            lambda client: (
                client.table("orders")
                .select("*")
                .eq("status", OrderStatus.PAYMENT_CONFIRMED.value)
                .order("paid_at")
                .limit(max(limit * 3, limit))
                .execute()
            )
        )
        now = datetime.now(UTC)
        ready: list[Order] = []
        for row in response.data or []:
            order = self._order(row)
            retry_at = order.processing_lease_until
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                if retry_at > now:
                    continue
            ready.append(order)
            if len(ready) >= limit:
                break
        return ready

    async def confirm_payment(
        self, order_id: UUID, tx_hash: str, tx_lt: int | None, sender: str | None
    ) -> Order | None:
        response = await self._db.rpc(
            "confirm_order_payment",
            {
                "p_order_id": str(order_id),
                "p_tx_hash": tx_hash,
                "p_tx_lt": tx_lt,
                "p_sender": sender,
            },
        )
        return self._order(response.data[0]) if response.data else None

    async def expire_due(self) -> list[Order]:
        response = await self._db.rpc("expire_due_orders", {})
        return [self._order(row) for row in response.data or []]

    async def review_stale_processing(self) -> list[Order]:
        response = await self._db.rpc("review_stale_processing_orders", {})
        return [self._order(row) for row in response.data or []]

    async def review_stale_profit_sweeps(self) -> None:
        await self._db.rpc("review_stale_profit_sweeps", {})

    async def cancel(self, order_id: UUID, user_id: int) -> Order | None:
        response = await self._db.rpc(
            "cancel_order", {"p_order_id": str(order_id), "p_user_id": user_id}
        )
        return self._order(response.data[0]) if response.data else None

    async def claim_fulfillment(
        self, order_id: UUID, lease_seconds: int
    ) -> tuple[Order, FulfillmentAttempt] | None:
        response = await self._db.rpc(
            "claim_order_fulfillment",
            {"p_order_id": str(order_id), "p_lease_seconds": lease_seconds},
        )
        if not response.data:
            return None
        row = response.data[0]
        order = self._order(row["order_data"])
        attempt = FulfillmentAttempt.model_validate(row["attempt_data"])
        return order, attempt

    async def mark_attempt_submitted(self, attempt_id: int) -> None:
        response = await self._db.run(
            lambda client: (
                client.table("fulfillment_attempts")
                .update({"status": FulfillmentAttemptStatus.SUBMITTED.value})
                .eq("id", attempt_id)
                .eq("status", FulfillmentAttemptStatus.CLAIMED.value)
                .execute()
            )
        )
        if not response.data:
            raise ConcurrentUpdateError("Fulfillment attempt is no longer claimable")

    async def complete_fulfillment(
        self,
        order_id: UUID,
        attempt_id: int,
        response_payload: dict[str, Any],
        fragment_order_id: str | None,
        http_status: int,
    ) -> Order:
        response = await self._db.rpc(
            "complete_order_fulfillment",
            {
                "p_order_id": str(order_id),
                "p_attempt_id": attempt_id,
                "p_response": response_payload,
                "p_fragment_order_id": fragment_order_id,
                "p_http_status": http_status,
            },
        )
        if not response.data:
            raise ConcurrentUpdateError("Order fulfillment completion lost its claim")
        return self._order(response.data[0])

    async def retry_fulfillment(
        self,
        order_id: UUID,
        attempt_id: int,
        *,
        error: str,
        response_payload: dict[str, Any] | None,
        retry_seconds: int,
    ) -> Order:
        response = await self._db.rpc(
            "retry_order_fulfillment",
            {
                "p_order_id": str(order_id),
                "p_attempt_id": attempt_id,
                "p_error": error[:4000],
                "p_response": response_payload,
                "p_retry_seconds": retry_seconds,
            },
        )
        if not response.data:
            raise ConcurrentUpdateError("Order fulfillment retry lost its claim")
        return self._order(response.data[0])

    async def claim_profit_sweep(self, order_id: UUID, amount: Decimal) -> bool:
        response = await self._db.rpc(
            "claim_profit_sweep",
            {"p_order_id": str(order_id), "p_amount": str(amount)},
        )
        return bool(response.data)

    async def complete_profit_sweep(self, order_id: UUID, message_hash: str) -> bool:
        response = await self._db.rpc(
            "complete_profit_sweep",
            {"p_order_id": str(order_id), "p_message_hash": message_hash},
        )
        return bool(response.data)

    async def fail_profit_sweep(self, order_id: UUID, error: str) -> bool:
        response = await self._db.rpc(
            "fail_profit_sweep",
            {"p_order_id": str(order_id), "p_error": error[:4000]},
        )
        return bool(response.data)

    async def fail_fulfillment(
        self,
        order_id: UUID,
        attempt_id: int,
        *,
        error: str,
        ambiguous: bool,
        response_payload: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> Order:
        response = await self._db.rpc(
            "fail_order_fulfillment",
            {
                "p_order_id": str(order_id),
                "p_attempt_id": attempt_id,
                "p_error": error[:4000],
                "p_ambiguous": ambiguous,
                "p_response": response_payload,
                "p_http_status": http_status,
            },
        )
        if not response.data:
            raise ConcurrentUpdateError("Order fulfillment failure lost its claim")
        return self._order(response.data[0])

    async def approve_retry(
        self, order_id: UUID, actor_id: int, reason: str
    ) -> Order | None:
        response = await self._db.rpc(
            "approve_order_retry",
            {"p_order_id": str(order_id), "p_actor_id": actor_id, "p_reason": reason},
        )
        return self._order(response.data[0]) if response.data else None
