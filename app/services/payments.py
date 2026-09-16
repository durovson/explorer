from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings
from app.core.enums import Currency
from app.core.exceptions import PaymentProviderTemporaryError
from app.models.entities import Order


def normalize_ton_address(address: str) -> str:
    value = address.strip()
    if ":" in value:
        workchain, account = value.split(":", 1)
        return f"{int(workchain)}:{account.lower()}"
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if len(raw) != 36:
            return value
        return f"{int.from_bytes(raw[1:2], 'big', signed=True)}:{raw[2:34].hex()}"
    except (ValueError, TypeError):
        return value


def same_address(left: str, right: str) -> bool:
    return normalize_ton_address(left) == normalize_ton_address(right)


def _decode_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        raw = bytes(value)
        if raw[:4] == b"\0\0\0\0":
            raw = raw[4:]
        return raw.decode("utf-8", errors="ignore")
    return ""


def ton_comment(message: dict[str, Any]) -> str:
    if isinstance(message.get("message"), str):
        return message["message"]
    data = message.get("msg_data") or {}
    if isinstance(data.get("text"), str):
        try:
            return base64.b64decode(data["text"]).decode("utf-8")
        except Exception:
            return data["text"]
    return ""


def jetton_comment(transfer: dict[str, Any]) -> str:
    decoded = transfer.get("decoded_forward_payload")
    if isinstance(decoded, dict):
        for key in ("text", "comment", "value"):
            result = _decode_text(decoded.get(key))
            if result:
                return result
    result = _decode_text(decoded)
    if result:
        return result
    return _decode_text(transfer.get("comment"))


@dataclass(frozen=True, slots=True)
class IncomingPayment:
    currency: Currency
    tx_hash: str
    amount_atomic: int
    destination: str
    memo: str
    tx_lt: int | None = None
    sender: str | None = None
    timestamp: int | None = None


class PaymentService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=20)

    @property
    def _headers(self) -> dict[str, str]:
        return (
            {"X-API-Key": self._settings.TONCENTER_API_KEY}
            if self._settings.TONCENTER_API_KEY
            else {}
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def scan(
        self, currency: Currency, oldest: datetime | None = None
    ) -> list[IncomingPayment]:
        try:
            return await (
                self._scan_ton(oldest)
                if currency is Currency.TON
                else self._scan_usdt(oldest)
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise PaymentProviderTemporaryError(str(exc)) from exc

    async def _scan_ton(self, oldest: datetime | None) -> list[IncomingPayment]:
        payments: list[IncomingPayment] = []
        seen: set[str] = set()
        cursor: dict[str, Any] = {}
        oldest_timestamp = int(oldest.timestamp()) - 30 if oldest else None
        for _ in range(self._settings.PAYMENT_MAX_PAGES):
            params: dict[str, Any] = {
                "address": self._settings.TON_RECEIVER_ADDRESS,
                "limit": min(self._settings.PAYMENT_SCAN_LIMIT, 100),
                **cursor,
            }
            if self._settings.TONCENTER_API_KEY:
                params["api_key"] = self._settings.TONCENTER_API_KEY
            response = await self._client.get(
                f"{self._settings.TONCENTER_V2_URL.rstrip('/')}/getTransactions",
                params=params,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise ValueError(f"TON Center rejected request: {body}")
            rows = body.get("result") or []
            for tx in rows:
                message = tx.get("in_msg") or {}
                destination = str(message.get("destination") or "")
                transaction_id = tx.get("transaction_id") or {}
                tx_hash = str(transaction_id.get("hash") or "")
                if tx_hash in seen or not same_address(
                    destination, self._settings.TON_RECEIVER_ADDRESS
                ):
                    continue
                seen.add(tx_hash)
                payments.append(
                    IncomingPayment(
                        currency=Currency.TON,
                        tx_hash=tx_hash,
                        amount_atomic=int(message.get("value") or 0),
                        destination=destination,
                        memo=ton_comment(message),
                        tx_lt=int(transaction_id.get("lt") or 0) or None,
                        sender=str(message.get("source") or "") or None,
                        timestamp=int(tx.get("utime") or 0) or None,
                    )
                )
            if not rows or len(rows) < params["limit"]:
                break
            last = rows[-1]
            last_id = last.get("transaction_id") or {}
            cursor = {"lt": last_id.get("lt"), "hash": last_id.get("hash")}
            if (
                oldest_timestamp is not None
                and int(last.get("utime") or 0) < oldest_timestamp
            ):
                break
        return payments

    async def _scan_usdt(self, oldest: datetime | None) -> list[IncomingPayment]:
        payments: list[IncomingPayment] = []
        limit = min(self._settings.PAYMENT_SCAN_LIMIT, 1000)
        for page in range(self._settings.PAYMENT_MAX_PAGES):
            params: dict[str, Any] = {
                "owner_address": self._settings.TON_RECEIVER_ADDRESS,
                "jetton_master": self._settings.USDT_MASTER_ADDRESS,
                "direction": "in",
                "limit": limit,
                "offset": page * limit,
                "sort": "desc",
            }
            if oldest:
                params["start_utime"] = int(oldest.timestamp()) - 30
            response = await self._client.get(
                f"{self._settings.TONCENTER_V3_URL.rstrip('/')}/jetton/transfers",
                params=params,
                headers=self._headers,
            )
            response.raise_for_status()
            rows = response.json().get("jetton_transfers") or []
            for transfer in rows:
                destination = str(transfer.get("destination") or "")
                master = str(transfer.get("jetton_master") or "")
                tx_hash = str(
                    transfer.get("transaction_hash") or transfer.get("trace_id") or ""
                )
                if transfer.get("transaction_aborted") or not tx_hash:
                    continue
                if not same_address(destination, self._settings.TON_RECEIVER_ADDRESS):
                    continue
                if not same_address(master, self._settings.USDT_MASTER_ADDRESS):
                    continue
                payments.append(
                    IncomingPayment(
                        currency=Currency.USDT,
                        tx_hash=tx_hash,
                        amount_atomic=int(transfer.get("amount") or 0),
                        destination=destination,
                        memo=jetton_comment(transfer),
                        tx_lt=int(transfer.get("transaction_lt") or 0) or None,
                        sender=str(transfer.get("source") or "") or None,
                        timestamp=int(transfer.get("transaction_now") or 0) or None,
                    )
                )
            if len(rows) < limit:
                break
        return payments

    @staticmethod
    def matches(order: Order, payment: IncomingPayment) -> bool:
        decimals = 9 if order.currency is Currency.TON else 6
        expected = int(order.amount * Decimal(10**decimals))
        return (
            payment.currency is order.currency
            and same_address(payment.destination, order.wallet_address)
            and payment.amount_atomic == expected
            and payment.memo == order.memo
            and (
                payment.timestamp is None
                or payment.timestamp >= int(order.created_at.timestamp()) - 30
            )
        )
