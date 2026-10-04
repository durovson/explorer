from __future__ import annotations

import inspect
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib import import_module
from typing import Any

import httpx

from app.config import Settings
from app.core.enums import ProductType
from app.core.exceptions import MarketappAmbiguousError, MarketappRejectedError
from app.models.entities import Order


@dataclass(frozen=True, slots=True)
class MarketappResult:
    payload: dict[str, Any]
    http_status: int
    external_order_id: str
    tx_hash: str | None = None


@dataclass(frozen=True, slots=True)
class RentalOffer:
    nft_address: str
    title: str
    days: int
    price_gram: Decimal
    photo_url: str | None
    raw: dict[str, Any]


class MarketappService:
    """Marketapp adapter.

    Read-only/preflight calls use the documented REST API directly. Mutating calls
    use the official ``marketapp-api`` SDK so the SDK can sign and broadcast TON
    transactions from the dedicated settlement wallet. The API token and wallet
    seed are read from environment settings only.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=settings.MARKETAPP_TIMEOUT_SECONDS)
        self._sdk: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.MARKETAPP_API_TOKEN)

    @property
    def auto_pay_configured(self) -> bool:
        return self._settings.marketapp_auto_pay_configured

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._settings.MARKETAPP_API_TOKEN,
            "Accept": "application/json",
        }

    def ensure_ready(self) -> None:
        if not self._settings.MARKETAPP_API_TOKEN:
            raise ValueError("Marketapp API не настроен")
        if not self._settings.MARKETAPP_WALLET_SEED:
            raise ValueError("Marketapp settlement wallet не настроен")
        if not self._settings.marketapp_ton_api_key:
            raise ValueError("Для Marketapp auto-pay нужен TON API key")

    async def close(self) -> None:
        await self._http.aclose()
        if self._sdk is None:
            return
        close = getattr(self._sdk, "close", None) or getattr(self._sdk, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def search_recipient(
        self, product: ProductType, recipient: str
    ) -> dict[str, Any]:
        if product is ProductType.STARS:
            path = "/v1/fragment/stars/recipient/"
        elif product is ProductType.PREMIUM:
            path = "/v1/fragment/premium/recipient/"
        elif product is ProductType.GRAM:
            path = "/v1/fragment/telegram-topup/recipient/"
        else:
            raise ValueError("Для аренды NFT recipient preflight не используется")
        username = recipient.lstrip("@")
        return await self._recipient_request(path, username)

    async def _recipient_request(self, path: str, username: str) -> dict[str, Any]:
        if not self.enabled:
            raise ValueError("Marketapp API не настроен")
        last_error: str = ""
        for body in ({"username": username}, {"recipient": username}):
            try:
                response = await self._http.post(
                    f"{self._settings.MARKETAPP_BASE_URL.rstrip('/')}{path}",
                    json=body,
                    headers=self._headers,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError("Marketapp recipient check недоступен") from exc
            if response.status_code == 422:
                last_error = self._safe_error(response)
                continue
            if response.status_code == 404:
                raise ValueError("Получатель не найден")
            if response.is_error:
                raise RuntimeError(
                    f"Marketapp recipient check HTTP {response.status_code}: "
                    f"{self._safe_error(response)}"
                )
            data = self._json_object(response)
            if data.get("error") or data.get("success") is False:
                raise ValueError(str(data.get("error") or "Получатель не найден"))
            return data
        raise RuntimeError(f"Marketapp recipient schema rejected request: {last_error}")

    async def rental_gifts(self, page: int = 0) -> tuple[list[RentalOffer], bool]:
        if not self.enabled:
            raise ValueError("Marketapp API не настроен")
        limit = self._settings.MARKETAPP_RENT_PAGE_SIZE
        params = {"limit": limit + 1, "offset": max(0, page) * limit}
        try:
            response = await self._http.get(
                f"{self._settings.MARKETAPP_BASE_URL.rstrip('/')}/v1/rent/gifts/",
                params=params,
                headers=self._headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("Каталог аренды Marketapp временно недоступен") from exc
        data = response.json()
        rows = self._rows(data)
        offers: list[RentalOffer] = []
        for row in rows[: limit + 1]:
            if not isinstance(row, dict):
                continue
            offer = self._normalize_offer(row)
            if offer is not None:
                offers.append(offer)
        return offers[:limit], len(offers) > limit or len(rows) > limit

    async def purchase(self, order: Order, idempotency_key: str) -> MarketappResult:
        # The idempotency key is persisted in Supabase. Marketapp mutating calls are
        # never auto-retried after an ambiguous result, which prevents double spend
        # even when the provider does not expose an idempotency request header.
        del idempotency_key
        self.ensure_ready()
        sdk = self._get_sdk()
        try:
            if order.product_type is ProductType.STARS:
                result = await self._buy_stars(sdk, order)
            elif order.product_type is ProductType.PREMIUM:
                result = await self._buy_premium(sdk, order)
            elif order.product_type is ProductType.GRAM:
                result = await self._telegram_topup(sdk, order)
            elif order.product_type is ProductType.NFT_RENT:
                result = await self._rent_nft(sdk, order)
            else:
                raise MarketappRejectedError(
                    f"Unsupported Marketapp product {order.product_type}"
                )
        except (MarketappRejectedError, MarketappAmbiguousError):
            raise
        except Exception as exc:
            self._raise_sdk_error(exc)
            raise AssertionError("unreachable")
        return self._normalize_result(result)

    def _get_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        try:
            module = import_module("MarketappAPI")
            client_class = getattr(module, "MarketappClient")
        except (ImportError, AttributeError) as exc:
            raise MarketappRejectedError(
                "marketapp-api package is not installed or incompatible"
            ) from exc
        self._sdk = client_class(
            api_token=self._settings.MARKETAPP_API_TOKEN,
            seed=self._settings.MARKETAPP_WALLET_SEED,
            api_key=self._settings.marketapp_ton_api_key,
            wallet_version=self._settings.MARKETAPP_WALLET_VERSION,
        )
        return self._sdk

    async def _buy_stars(self, sdk: Any, order: Order) -> Any:
        username = order.recipient.lstrip("@")
        quantity = int(order.stars_amount or 0)
        body = self._build_body(
            "BuyStarsBody",
            order.provider_payload,
            username=username,
            recipient=username,
            quantity=quantity,
            stars=quantity,
            amount=quantity,
            show_sender=False,
            currency="GRAM",
        )
        return await self._invoke(
            sdk.buy_stars,
            [
                ((body,), {"auto_pay": True}),
                ((), {"body": body, "auto_pay": True}),
                ((), {"username": username, "quantity": quantity, "auto_pay": True}),
                ((username, quantity), {"auto_pay": True}),
            ],
        )

    async def _buy_premium(self, sdk: Any, order: Order) -> Any:
        username = order.recipient.lstrip("@")
        months = int(order.premium_months or 0)
        body = self._build_body(
            "BuyPremiumBody",
            order.provider_payload,
            username=username,
            recipient=username,
            months=months,
            duration=months,
            show_sender=False,
            currency="GRAM",
        )
        return await self._invoke(
            sdk.buy_premium,
            [
                ((body,), {"auto_pay": True}),
                ((), {"body": body, "auto_pay": True}),
                ((), {"username": username, "months": months, "auto_pay": True}),
                ((username, months), {"auto_pay": True}),
            ],
        )

    async def _telegram_topup(self, sdk: Any, order: Order) -> Any:
        username = order.recipient.lstrip("@")
        amount = float(order.gram_amount or Decimal("0"))
        body = self._build_body(
            "TelegramTopupBody",
            order.provider_payload,
            username=username,
            recipient=username,
            amount=amount,
            quantity=amount,
            currency="GRAM",
        )
        return await self._invoke(
            sdk.telegram_topup,
            [
                ((body,), {"auto_pay": True}),
                ((), {"body": body, "auto_pay": True}),
                ((), {"username": username, "amount": amount, "auto_pay": True}),
                ((username, amount), {"auto_pay": True}),
            ],
        )

    async def _rent_nft(self, sdk: Any, order: Order) -> Any:
        nft_address = order.nft_address or ""
        days = int(order.rent_days or 0)
        body = self._build_body(
            "RentNFTBody",
            order.provider_payload,
            nft_address=nft_address,
            address=nft_address,
            days=days,
            duration=days,
            period=days,
            price=float(order.provider_price_gram or Decimal("0")),
            currency="GRAM",
        )
        return await self._invoke(
            sdk.rent_nft,
            [
                ((nft_address, body), {"auto_pay": True}),
                ((body,), {"auto_pay": True}),
                ((), {"nft_address": nft_address, "body": body, "auto_pay": True}),
                ((), {"nft_address": nft_address, "days": days, "auto_pay": True}),
                ((nft_address, days), {"auto_pay": True}),
            ],
        )

    @staticmethod
    async def _invoke(method: Any, variants: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> Any:
        signature = inspect.signature(method)
        bind_errors: list[str] = []
        for args, kwargs in variants:
            try:
                signature.bind(*args, **kwargs)
            except TypeError as exc:
                bind_errors.append(str(exc))
                continue
            result = method(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result
        raise MarketappRejectedError(
            "Installed marketapp-api has an unsupported method signature: "
            + "; ".join(bind_errors[-2:])
        )

    @staticmethod
    def _build_body(model_name: str, source: dict[str, Any], **semantic: Any) -> Any:
        try:
            models = import_module("MarketappAPI.types.models")
            model = getattr(models, model_name)
        except (ImportError, AttributeError):
            return {**source, **semantic}
        fields = getattr(model, "model_fields", {})
        values: dict[str, Any] = {}
        source_lower = {str(k).lower(): v for k, v in source.items()}
        semantic_lower = {str(k).lower(): v for k, v in semantic.items()}
        for name, field in fields.items():
            alias = str(getattr(field, "alias", "") or "")
            for candidate in (name.lower(), alias.lower()):
                if candidate and candidate in source_lower:
                    values[name] = source_lower[candidate]
                    break
                if candidate and candidate in semantic_lower:
                    values[name] = semantic_lower[candidate]
                    break
        try:
            return model.model_validate(values)
        except Exception as exc:
            # If the exact API response fields from preflight/catalog are accepted
            # by this SDK version, prefer them before declaring a contract mismatch.
            try:
                return model.model_validate({**source, **semantic})
            except Exception:
                raise MarketappRejectedError(
                    f"Cannot build {model_name} for installed marketapp-api: {exc}"
                ) from exc

    def _normalize_result(self, result: Any) -> MarketappResult:
        payload = self._dump(result)
        confirmed = payload.get("confirmed")
        if confirmed is False:
            raise MarketappAmbiguousError(
                "Marketapp transaction was sent but not confirmed",
                response=payload,
            )
        tx_hash = self._first_string(payload, "tx_hash", "transaction_hash", "hash")
        if not tx_hash and any(key in payload for key in ("transaction", "messages", "valid_until")):
            raise MarketappRejectedError(
                "Marketapp returned an unsigned transaction; auto-pay wallet is not active",
                response=payload,
            )
        if payload.get("success") is False:
            raise MarketappRejectedError(
                str(payload.get("error") or "Marketapp rejected operation"),
                response=payload,
            )
        external_id = self._first_string(
            payload, "invoice_id", "order_id", "id", "transaction_id"
        ) or tx_hash
        if not external_id:
            # A confirmed SDK result may only expose balance/seqno. Keep an auditable
            # synthetic id while persisting the full response.
            external_id = "marketapp-confirmed"
        return MarketappResult(payload, 200, external_id, tx_hash)

    @staticmethod
    def _raise_sdk_error(exc: Exception) -> None:
        name = exc.__class__.__name__
        message = str(exc)[:2000]
        if name in {"ValidationError", "ConfigurationError", "WalletError"}:
            raise MarketappRejectedError(message) from exc
        if name in {"TransactionError", "ConfirmationTimeout", "SeqnoError", "APIError"}:
            raise MarketappAmbiguousError(message) from exc
        raise MarketappAmbiguousError(f"Unexpected Marketapp error: {message}") from exc

    @staticmethod
    def _dump(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {"result": dumped}
        if hasattr(value, "__dict__"):
            return {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return {"result": str(value)}

    @staticmethod
    def _rows(data: Any) -> list[Any]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("items", "results", "gifts", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = MarketappService._rows(value)
                if nested:
                    return nested
        return []

    @classmethod
    def _normalize_offer(cls, raw: dict[str, Any]) -> RentalOffer | None:
        address = cls._first_string(raw, "nft_address", "address", "nft")
        if not address:
            return None
        title = cls._first_string(raw, "name", "title", "collection_name") or address[:12]
        photo = cls._first_string(raw, "image", "image_url", "photo", "photo_url", "preview")
        days, price = cls._rent_terms(raw)
        if days <= 0 or price <= 0:
            return None
        return RentalOffer(address, title, days, price, photo, raw)

    @classmethod
    def _rent_terms(cls, raw: dict[str, Any]) -> tuple[int, Decimal]:
        prices = raw.get("prices") or raw.get("rent_prices") or raw.get("periods")
        if isinstance(prices, dict):
            for raw_days, raw_price in prices.items():
                days = cls._to_int(raw_days)
                price = cls._to_decimal(raw_price)
                if days > 0 and price > 0:
                    return days, price
        if isinstance(prices, list):
            for item in prices:
                if not isinstance(item, dict):
                    continue
                days = cls._first_int(item, "days", "duration", "period", "rent_days")
                price = cls._first_decimal(item, "price", "amount", "gram", "gram_price")
                if days > 0 and price > 0:
                    return days, price
        days = cls._first_int(raw, "days", "duration", "period", "rent_days", "min_days")
        price = cls._first_decimal(raw, "price", "rent_price", "min_price", "gram_price")
        if days <= 0 and cls._first_decimal(raw, "price_per_day") > 0:
            days = 7
            price = cls._first_decimal(raw, "price_per_day") * days
        return days, price

    @staticmethod
    def _first_string(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)):
                return str(value)
        return None

    @classmethod
    def _first_int(cls, data: dict[str, Any], *keys: str) -> int:
        for key in keys:
            result = cls._to_int(data.get(key))
            if result > 0:
                return result
        return 0

    @classmethod
    def _first_decimal(cls, data: dict[str, Any], *keys: str) -> Decimal:
        for key in keys:
            result = cls._to_decimal(data.get(key))
            if result > 0:
                return result
        return Decimal("0")

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(str(value).split()[0])
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        try:
            if isinstance(value, dict):
                for key in ("GRAM", "gram", "price", "amount"):
                    if key in value:
                        return Decimal(str(value[key]))
                return Decimal("0")
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Marketapp вернул не-JSON ответ") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Marketapp вернул неожиданный формат ответа")
        return data

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                return str(data.get("detail") or data.get("error") or data)[:500]
        except ValueError:
            pass
        return f"HTTP {response.status_code}"
