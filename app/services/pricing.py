from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from MarketappAPI import MarketappClient
from MarketappAPI.types.models import StarsPriceBody

from app.config import Settings
from app.core.enums import Currency, ProductType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PriceQuote:
    base: Decimal
    total: Decimal


class PriceService:
    CACHE_SECONDS = 45

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[tuple[str, int], tuple[float, dict[Currency, Decimal]]] = {}

    @staticmethod
    def _positive_decimal(obj: object, *names: str) -> Decimal:
        for name in names:
            value = getattr(obj, name, None)
            if value is None:
                continue
            try:
                result = Decimal(str(value))
            except Exception:
                continue
            if result > 0:
                return result
        raise RuntimeError("Провайдер временно не вернул корректную цену")

    async def _base_prices(
        self,
        product: ProductType,
        *,
        stars_amount: int | None,
        premium_months: int | None,
    ) -> dict[Currency, Decimal]:
        quantity = stars_amount if product is ProductType.STARS else premium_months
        if not isinstance(quantity, int):
            raise ValueError("Не задано количество")
        key = (product.value, quantity)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] <= self.CACHE_SECONDS:
            return cached[1]

        started = time.perf_counter()
        client = MarketappClient(
            api_token=self._settings.MARKETAPP_API_TOKEN,
            timeout=self._settings.MARKETAPP_TIMEOUT_SECONDS,
        )
        if product is ProductType.STARS:
            if not 50 <= quantity <= 10_000:
                raise ValueError("Количество Stars должно быть от 50 до 10 000")
            response = await client.get_stars_prices(StarsPriceBody(quantity=quantity))
            ton = self._positive_decimal(response, "gram", "ton")
            usdt = self._positive_decimal(response, "usd")
        else:
            if quantity not in {3, 6, 12}:
                raise ValueError("Срок Premium должен быть 3, 6 или 12 месяцев")
            response = await client.get_premium_price()
            option = getattr(response, f"months{quantity}", None)
            if option is None:
                raise RuntimeError("Этот тариф Premium временно недоступен")
            ton = self._positive_decimal(option, "gram", "ton")
            usdt = self._positive_decimal(option, "usd")

        result = {Currency.TON: ton, Currency.USDT: usdt}
        self._cache[key] = (time.monotonic(), result)
        logger.info(
            "marketapp_price_ms=%.1f product=%s quantity=%d",
            (time.perf_counter() - started) * 1000, product.value, quantity,
        )
        return result

    @staticmethod
    def _with_fixed_markup(base: Decimal, currency: Currency) -> Decimal:
        # Gas, supplier expenses and rounding are covered by the single 5% fee.
        # Floor payable totals to 4 places so rounding never increases the fee.
        return (base * Decimal("1.05")).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

    async def quote(
        self,
        product: ProductType,
        currency: Currency,
        *,
        stars_amount: int | None = None,
        premium_months: int | None = None,
    ) -> PriceQuote:
        prices = await self._base_prices(
            product,
            stars_amount=stars_amount,
            premium_months=premium_months,
        )
        base = prices[currency]
        return PriceQuote(base=base, total=self._with_fixed_markup(base, currency))

    async def calculate(
        self,
        product: ProductType,
        currency: Currency,
        *,
        stars_amount: int | None = None,
        premium_months: int | None = None,
    ) -> Decimal:
        quote = await self.quote(
            product,
            currency,
            stars_amount=stars_amount,
            premium_months=premium_months,
        )
        return quote.total
