from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from app.api.notifier import OrderNotifier
from app.config import Settings
from app.core.enums import Currency
from app.core.exceptions import (
    FragmentAmbiguousError,
    FragmentRejectedError,
    FragmentTemporaryError,
)
from app.repositories.orders import OrderRepository
from app.repositories.payments import PaymentRepository
from app.services.fragment import FragmentService
from app.services.payments import PaymentService
from app.services.settlement import SettlementService

logger = logging.getLogger(__name__)
_TON_SCANNER = "ton-receiver-v1"


class WorkerManager:
    """Independent loops: one provider/order failure cannot block the others."""

    def __init__(
        self,
        settings: Settings,
        orders: OrderRepository,
        payment_events: PaymentRepository,
        payments: PaymentService,
        fragment: FragmentService,
        settlement: SettlementService,
        notifier: OrderNotifier,
    ):
        self._settings = settings
        self._orders = orders
        self._payment_events = payment_events
        self._payments = payments
        self._fragment = fragment
        self._settlement = settlement
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
            "ton-payments": self._ton_payment_loop,
            "usdt-payments": lambda: self._legacy_payment_loop(Currency.USDT),
            "order-expiry": self._expiry_loop,
            "marketapp-fulfillment": self._fulfillment_loop,
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
                logger.exception("Worker %s iteration failed; retry in %ss", name, delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _ton_payment_loop(self) -> None:
        async def run_once() -> None:
            cursor = await self._payment_events.get_cursor(_TON_SCANNER)
            open_orders = await self._orders.list_open(
                Currency.TON, self._settings.ORDER_BATCH_SIZE
            )
            if cursor is None and not open_orders:
                return
            oldest = min((order.created_at for order in open_orders), default=None)
            batch = await self._payments.scan_ton_since(
                cursor.last_lt if cursor else None,
                cursor.last_hash if cursor else None,
                oldest=oldest if cursor is None else None,
            )
            for payment in batch.payments:
                try:
                    order, matched, reason = await self._payment_events.ingest_ton(
                        tx_hash=payment.tx_hash,
                        tx_lt=payment.tx_lt,
                        amount_atomic=payment.amount_atomic,
                        destination=payment.destination,
                        sender=payment.sender,
                        memo=payment.memo,
                        timestamp=payment.timestamp,
                    )
                    if matched and order is not None:
                        await self._notifier.order_changed(order)
                    elif reason not in {"unknown_memo", "already_processed"}:
                        logger.info(
                            "Observed TON deposit was not matched: tx=%s reason=%s",
                            payment.tx_hash,
                            reason,
                        )
                except Exception:
                    logger.exception("Could not ingest TON payment %s", payment.tx_hash)
                    raise

            if batch.newest_lt is not None:
                await self._payment_events.save_cursor(
                    _TON_SCANNER,
                    self._settings.TON_RECEIVER_ADDRESS,
                    batch.newest_lt,
                    batch.newest_hash,
                )

        await self._repeat("ton-payments", run_once)

    async def _legacy_payment_loop(self, currency: Currency) -> None:
        name = f"{currency.value.lower()}-payments"

        async def run_once() -> None:
            orders = await self._orders.list_open(currency, self._settings.ORDER_BATCH_SIZE)
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
            await self._orders.review_stale_profit_sweeps()
            for order in changed:
                try:
                    await self._notifier.order_changed(order)
                except Exception:
                    logger.exception("Could not notify expired order %s", order.id)

        await self._repeat("order-expiry", run_once)

    async def _sweep_profit(self, order, provider_debit_ton: Decimal | None) -> None:
        if order.currency is not Currency.TON:
            return
        if provider_debit_ton is None:
            logger.warning(
                "Marketapp did not expose an exact wallet debit for order %s; service margin stays in the operational wallet",
                order.id,
            )
            return
        reserved_reward = await self._orders.referral_reward_for_order(order.id)
        margin = order.amount - provider_debit_ton - reserved_reward
        if margin <= 0:
            logger.warning(
                "No positive realized margin for order %s: paid=%s provider_debit=%s",
                order.id,
                order.amount,
                provider_debit_ton,
            )
            return
        margin = margin.quantize(Decimal("0.000000001"))
        if not await self._orders.claim_profit_sweep(order.id, margin):
            return
        try:
            message_hash = await self._settlement.transfer_profit(order.id, margin)
        except Exception as exc:
            await self._orders.fail_profit_sweep(order.id, str(exc))
            logger.exception("Profit sweep requires manual review for %s", order.id)
            return
        await self._orders.complete_profit_sweep(order.id, message_hash)

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
                    try:
                        result = await self._fragment.purchase(order, attempt.idempotency_key)
                    except FragmentTemporaryError as exc:
                        retry = await self._orders.retry_fulfillment(
                            order.id,
                            attempt.id,
                            error=str(exc),
                            response_payload=exc.response,
                            retry_seconds=exc.retry_after_seconds,
                        )
                        # Keep the user-facing card current even while an already
                        # paid order waits for a safe pre-broadcast retry. This also
                        # migrates any legacy image card to the new text-only UI.
                        await self._notifier.order_changed(retry)
                        logger.info(
                            "Marketapp purchase deferred for order %s: %s", retry.id, exc
                        )
                    except FragmentRejectedError as exc:
                        failed = await self._orders.fail_fulfillment(
                            order.id,
                            attempt.id,
                            error=str(exc),
                            ambiguous=False,
                            response_payload=exc.response,
                            http_status=exc.http_status,
                        )
                        await self._notifier.order_changed(failed)
                    except FragmentAmbiguousError as exc:
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
                            result.http_status,
                        )
                        await self._notifier.order_changed(completed)
                        await self._sweep_profit(completed, result.provider_debit_ton)
                except Exception:
                    logger.exception(
                        "Fulfillment iteration failed for order %s", pending.id
                    )

        await self._repeat("marketapp-fulfillment", run_once)
