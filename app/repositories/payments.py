from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.database import SupabaseDatabase
from app.models.entities import Order


@dataclass(frozen=True, slots=True)
class PaymentCursor:
    last_lt: int
    last_hash: str | None


class PaymentRepository:
    """Durable GRNT-style payment cursor and immutable deposit ingestion."""

    def __init__(self, database: SupabaseDatabase):
        self._db = database

    async def get_cursor(self, scanner: str) -> PaymentCursor | None:
        response = await self._db.run(
            lambda client: (
                client.table("payment_scanner_cursors")
                .select("last_lt,last_hash")
                .eq("scanner", scanner)
                .limit(1)
                .execute()
            )
        )
        if not response.data:
            return None
        row = response.data[0]
        return PaymentCursor(last_lt=int(row["last_lt"]), last_hash=row.get("last_hash"))

    async def save_cursor(
        self,
        scanner: str,
        account_address: str,
        last_lt: int,
        last_hash: str | None,
    ) -> PaymentCursor:
        response = await self._db.run(
            lambda client: (
                client.table("payment_scanner_cursors")
                .upsert(
                    {
                        "scanner": scanner,
                        "account_address": account_address,
                        "last_lt": last_lt,
                        "last_hash": last_hash,
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                    on_conflict="scanner",
                )
                .execute()
            )
        )
        row = response.data[0]
        return PaymentCursor(last_lt=int(row["last_lt"]), last_hash=row.get("last_hash"))

    async def ingest_ton(
        self,
        *,
        tx_hash: str,
        tx_lt: int | None,
        amount_atomic: int,
        destination: str,
        sender: str | None,
        memo: str,
        timestamp: int | None,
    ) -> tuple[Order | None, bool, str]:
        observed_at = (
            datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
            if timestamp is not None
            else None
        )
        response = await self._db.rpc(
            "ingest_ton_payment",
            {
                "p_tx_hash": tx_hash,
                "p_tx_lt": tx_lt,
                "p_amount_atomic": amount_atomic,
                "p_destination": destination,
                "p_sender": sender,
                "p_memo": memo,
                "p_observed_at": observed_at,
            },
        )
        row = response.data[0] if response.data else {}
        order_data = row.get("order_data")
        return (
            Order.model_validate(order_data) if order_data else None,
            bool(row.get("matched")),
            str(row.get("reason") or "unknown"),
        )
