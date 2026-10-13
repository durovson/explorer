from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from MarketappAPI import MarketappClient
from MarketappAPI.types.models import BuyPremiumBody, BuyStarsBody, SearchRecipientBody
from ton_core import NetworkGlobalID
from tonutils.clients import ToncenterClient
from tonutils.contracts import WalletV4R2, WalletV5R1

from app.config import Settings
from app.core.enums import ProductType
from app.core.exceptions import (
    FragmentAmbiguousError,
    FragmentRejectedError,
    FragmentTemporaryError,
)
from app.models.entities import Order
from app.services.payments import same_address

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FragmentResult:
    """Legacy result name retained for repository compatibility."""

    payload: dict[str, Any]
    http_status: int
    external_order_id: str
    provider_debit_ton: Decimal | None = None


class FragmentService:
    """Marketapp purchase adapter; legacy class name keeps DB/RPC compatibility."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._wallet_check_lock = asyncio.Lock()
        self._derived_wallet_address: str | None = None

    def _client(self, *, wallet: bool) -> MarketappClient:
        kwargs: dict[str, Any] = {
            "api_token": self._settings.MARKETAPP_API_TOKEN,
            "api_provider": self._settings.MARKETAPP_API_PROVIDER,
            "timeout": self._settings.MARKETAPP_TIMEOUT_SECONDS,
        }
        if wallet:
            kwargs.update(
                seed=self._settings.MARKETAPP_WALLET_SEED,
                api_key=self._settings.TONCENTER_API_KEY,
                wallet_version=self._settings.MARKETAPP_WALLET_VERSION,
            )
        return MarketappClient(**kwargs)

    async def close(self) -> None:
        return None

    async def _wallet_address(self) -> str:
        """Derive the address Marketapp will sign from, without exposing the seed."""
        if self._derived_wallet_address is not None:
            return self._derived_wallet_address
        async with self._wallet_check_lock:
            if self._derived_wallet_address is not None:
                return self._derived_wallet_address
            client = ToncenterClient(
                network=NetworkGlobalID.MAINNET,
                api_key=self._settings.TONCENTER_API_KEY,
                rps_limit=self._settings.TONCENTER_RPS_LIMIT,
            )
            await client.connect()
            try:
                wallet_cls = (
                    WalletV5R1
                    if self._settings.MARKETAPP_WALLET_VERSION == "V5R1"
                    else WalletV4R2
                )
                wallet, _, _, _ = wallet_cls.from_mnemonic(
                    client, self._settings.MARKETAPP_WALLET_SEED
                )
                self._derived_wallet_address = wallet.address.to_str(
                    is_bounceable=False
                )
                return self._derived_wallet_address
            finally:
                await client.close()

    async def _ensure_operational_wallet_matches_receiver(
        self, attempt_key: str
    ) -> None:
        try:
            derived = await self._wallet_address()
        except Exception as exc:
            logger.exception("Could not derive Marketapp operational wallet")
            raise FragmentTemporaryError(
                "Не удалось проверить операционный кошелёк Marketapp. Проверьте seed и версию кошелька.",
                response={"attempt_key": attempt_key},
                retry_after_seconds=300,
            ) from exc

        receiver = self._settings.TON_RECEIVER_ADDRESS
        if same_address(derived, receiver):
            return
        logger.error(
            "Marketapp signing wallet does not match TON receiver: derived=%s receiver=%s version=%s",
            derived,
            receiver,
            self._settings.MARKETAPP_WALLET_VERSION,
        )
        raise FragmentTemporaryError(
            "Кошелёк Marketapp не совпадает с адресом приёма TON. Проверьте MARKETAPP_WALLET_SEED и MARKETAPP_WALLET_VERSION.",
            response={
                "attempt_key": attempt_key,
                "wallet_mismatch": True,
                "derived_wallet_address": derived,
                "receiver_wallet_address": receiver,
            },
            retry_after_seconds=300,
        )

    async def user_info(self, recipient: str, product: ProductType) -> dict[str, Any]:
        username = recipient.lstrip("@")
        try:
            client = self._client(wallet=False)
            body = SearchRecipientBody(username=username)
            response = (
                await client.search_stars_recipient(body)
                if product is ProductType.STARS
                else await client.search_premium_recipient(body)
            )
        except Exception as exc:
            message = str(exc)
            lower = message.lower()
            if "not found" in lower or "404" in lower:
                raise ValueError("username не найден") from exc
            if product is ProductType.PREMIUM and (
                "already" in lower or "subscribed" in lower or "active" in lower
            ):
                raise ValueError("у получателя уже активен Premium") from exc
            raise RuntimeError("Проверка получателя временно недоступна") from exc

        if response is None:
            raise ValueError("username не найден")
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        return {"username": username}

    @staticmethod
    def _payload(result: object, attempt_key: str) -> dict[str, Any]:
        if hasattr(result, "model_dump"):
            payload = result.model_dump(mode="json")
            if isinstance(payload, dict):
                return {**payload, "attempt_key": attempt_key}
        return {
            "tx_hash": str(getattr(result, "tx_hash", "") or ""),
            "confirmed": bool(getattr(result, "confirmed", False)),
            "attempt_key": attempt_key,
        }

    @staticmethod
    def _provider_debit(result: object, order: Order) -> Decimal | None:
        """Return the actual wallet debit for this purchase, including chain fees."""
        before = getattr(result, "balance_before", None)
        after = getattr(result, "balance_after", None)
        if before is None or after is None:
            return None
        try:
            debit = Decimal(str(before)) - Decimal(str(after))
        except Exception:
            return None
        if debit <= 0 or debit > order.amount:
            return None
        return debit.quantize(Decimal("0.000000001"))

    @staticmethod
    def _is_prebroadcast_balance_error(exc: Exception) -> bool:
        text = str(exc).lower()
        name = type(exc).__name__.lower()
        return (
            "insufficient balance" in text
            or "not enough balance" in text
            or ("wallet" in name and "balance" in text)
        )

    async def purchase(self, order: Order, idempotency_key: str) -> FragmentResult:
        await self._ensure_operational_wallet_matches_receiver(idempotency_key)

        username = order.recipient.lstrip("@")
        try:
            client = self._client(wallet=True)
            if order.product_type is ProductType.STARS:
                result = await client.buy_stars(
                    BuyStarsBody(username=username, quantity=order.stars_amount),
                    auto_pay=True,
                )
            else:
                result = await client.buy_premium(
                    BuyPremiumBody(username=username, months=order.premium_months),
                    auto_pay=True,
                )
        except Exception as exc:
            response = {"attempt_key": idempotency_key}
            if type(exc).__name__ == "ValidationError":
                raise FragmentRejectedError(
                    f"Покупка отклонена: {str(exc)[:500]}",
                    response=response,
                    http_status=422,
                ) from exc
            if self._is_prebroadcast_balance_error(exc):
                raise FragmentTemporaryError(
                    f"Средства ещё не доступны для покупки: {str(exc)[:500]}",
                    response=response,
                    retry_after_seconds=60,
                ) from exc
            raise FragmentAmbiguousError(
                f"Результат покупки требует проверки: {str(exc)[:500]}",
                response=response,
            ) from exc

        payload = self._payload(result, idempotency_key)
        tx_hash = str(getattr(result, "tx_hash", "") or "")
        confirmed = bool(getattr(result, "confirmed", False))
        provider_debit = self._provider_debit(result, order)
        if provider_debit is not None:
            payload["provider_debit_ton"] = str(provider_debit)
        if not confirmed or not tx_hash:
            raise FragmentAmbiguousError(
                "Провайдер не вернул подтверждённую транзакцию",
                response=payload,
                http_status=200,
            )
        return FragmentResult(
            payload=payload,
            http_status=200,
            external_order_id=tx_hash,
            provider_debit_ton=provider_debit,
        )
