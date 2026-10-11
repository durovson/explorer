from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from MarketappAPI import MarketappClient
from MarketappAPI.types.models import BuyPremiumBody, BuyStarsBody, SearchRecipientBody

from app.config import Settings
from app.core.enums import ProductType
from app.core.exceptions import FragmentAmbiguousError, FragmentRejectedError
from app.models.entities import Order


@dataclass(frozen=True, slots=True)
class FragmentResult:
    """Legacy result name retained for repository compatibility."""

    payload: dict[str, Any]
    http_status: int
    external_order_id: str


class FragmentService:
    """Marketapp provider adapter; legacy class name keeps DB/RPC compatibility."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _client(self, *, wallet: bool) -> MarketappClient:
        kwargs: dict[str, Any] = {
            "api_token": self._settings.MARKETAPP_API_TOKEN,
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

    async def user_info(self, recipient: str, product: ProductType) -> dict[str, Any]:
        username = recipient.lstrip("@")
        try:
            async with self._client(wallet=False) as client:
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
            raise RuntimeError(f"Marketapp preflight unavailable: {message[:160]}") from exc

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

    async def purchase(self, order: Order, idempotency_key: str) -> FragmentResult:
        username = order.recipient.lstrip("@")
        try:
            async with self._client(wallet=True) as client:
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
            if type(exc).__name__ == "ValidationError":
                raise FragmentRejectedError(
                    f"Marketapp rejected purchase: {str(exc)[:500]}",
                    response={"attempt_key": idempotency_key},
                    http_status=422,
                ) from exc
            raise FragmentAmbiguousError(
                f"Marketapp purchase outcome is unknown: {str(exc)[:500]}",
                response={"attempt_key": idempotency_key},
            ) from exc

        payload = self._payload(result, idempotency_key)
        tx_hash = str(getattr(result, "tx_hash", "") or "")
        confirmed = bool(getattr(result, "confirmed", False))
        if not confirmed or not tx_hash:
            raise FragmentAmbiguousError(
                "Marketapp returned no confirmed blockchain transaction",
                response=payload,
                http_status=200,
            )
        return FragmentResult(payload=payload, http_status=200, external_order_id=tx_hash)
