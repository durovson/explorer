from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.api.notifier import OrderNotifier
from app.config import Settings
from app.core.enums import Currency, OrderProvider
from app.core.exceptions import ProviderAmbiguousError, ProviderRejectedError
from app.repositories.orders import OrderRepository
from app.services.fragment import FragmentService
from app.services.marketapp import MarketappService
from app.services.payments import PaymentService

logger = logging.getLogger(__name__)


class WorkerManager:
    """Independent loops: one provider/order failure cannot block the others."""

    def __init__(
        self,
        settings: Settings,
        orders: OrderRepository,
        payments: PaymentService,
        fragment: FragmentService,
        marketapp: MarketappService,
        notifier: OrderNotifier,
    ):
        self._settings = settings
        self._orders = orders
        self._payments = payments
        self._fragment = fragment
        self._marketapp = marketapp
        self._notifier = notifier
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self.last_success: dict[str, datetime] = {}

    @property
    def healthy(self) -> bool:
        return bool(self._tasks) and all(not task.done() for task in self._tasks)

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        workers = {
            "ton-payments": lambda: self._payment_loop(Currency.TON),
            "usdt-payments": lambda: self._payment_loop(Currency.USDT),
            "order-expiry": self._expiry_loop,
            "provider-fulfillment": self._fulfillment_loop,
        }
        self._tasks = {
            asyncio.create_task(worker(), name=name) for name, worker in workers.items()
        }

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _repeat(self, name: str, callback: Callable[[], Awaitable[None]]) -> None:
        failures = 0
        while not self._stop.is_set():
            delay = self._settings.WORKER_INTERVAL_SECONDS
            try:
                await callback()
                self.last_success[name] = datetime.now(UTC)
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                delay = min(delay * 2 ** min(failures, 5), 300)
                logger.exception(
                    "Worker %s iteration failed; retry in %ss", name, delay
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _payment_loop(self, currency: Currency) -> None:
        name = f"{currency.value.lower()}-payments"

        async def run_once() -> None:
            orders = await self._orders.list_open(
                currency, self._settings.ORDER_BATCH_SIZE
            )
            if not orders:
                return
            payments = await self._payments.scan(
                currency, min(order.created_at for order in orders)
            )
            by_memo = {payment.memo: payment for payment in payments if payment.memo}
            for order in orders:
                payment = by_memo.get(order.memo)
                if payment is None or not self._payments.matches(order, payment):
                    continue
                try:
                    confirmed = await self._orders.confirm_payment(
                        order.id, payment.tx_hash, payment.tx_lt, payment.sender
                    )
                    if confirmed:
                        await self._notifier.order_changed(confirmed)
                except Exception:
                    logger.exception("Could not confirm payment for order %s", order.id)

        await self._repeat(name, run_once)

    async def _expiry_loop(self) -> None:
        async def run_once() -> None:
            changed = await self._orders.expire_due()
            changed.extend(await self._orders.review_stale_processing())
            for order in changed:
                try:
                    await self._notifier.order_changed(order)
                except Exception:
                    logger.exception("Could not notify expired order %s", order.id)

        await self._repeat("order-expiry", run_once)

    async def _fulfillment_loop(self) -> None:
        async def run_once() -> None:
            ready = await self._orders.list_ready_for_fulfillment(
                self._settings.ORDER_BATCH_SIZE
            )
            for pending in ready:
                try:
                    claimed = await self._orders.claim_fulfillment(
                        pending.id, self._settings.FULFILLMENT_LEASE_SECONDS
                    )
                    if claimed is None:
                        continue
                    order, attempt = claimed
                    await self._orders.mark_attempt_submitted(attempt.id)
                    provider = (
                        self._fragment
                        if order.provider is OrderProvider.FRAGMENT
                        else self._marketapp
                    )
                    try:
                        result = await provider.purchase(order, attempt.idempotency_key)
                    except ProviderRejectedError as exc:
                        failed = await self._orders.fail_fulfillment(
                            order.id,
                            attempt.id,
                            error=str(exc),
                            ambiguous=False,
                            response_payload=exc.response,
                            http_status=exc.http_status,
                        )
                        await self._notifier.order_changed(failed)
                    except ProviderAmbiguousError as exc:
                        review = await self._orders.fail_fulfillment(
                            order.id,
                            attempt.id,
                            error=str(exc),
                            ambiguous=True,
                            response_payload=exc.response,
                            http_status=exc.http_status,
                        )
                        await self._notifier.order_changed(review)
                    else:
                        completed = await self._orders.complete_fulfillment(
                            order.id,
                            attempt.id,
                            result.payload,
                            result.external_order_id,
                            getattr(result, "tx_hash", None),
                            result.http_status,
                        )
                        await self._notifier.order_changed(completed)
                except Exception:
                    logger.exception(
                        "Fulfillment iteration failed for order %s", pending.id
                    )

        await self._repeat("provider-fulfillment", run_once)
