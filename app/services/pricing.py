from __future__ import annotations

import time
from decimal import ROUND_UP, Decimal

from MarketappAPI import MarketappClient
from MarketappAPI.types.models import StarsPriceBody

from app.config import Settings
from app.core.enums import Currency, ProductType

TON_MARKUP_NUMERATOR = Decimal("539612")
TON_MARKUP_DENOMINATOR = Decimal("10229388")
USDT_MARKUP_NUMERATOR = Decimal("19")
USDT_MARKUP_DENOMINATOR = Decimal("75")


class PriceService:
    CACHE_SECONDS = 20

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
        raise RuntimeError("Marketapp returned an invalid price")

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

        async with MarketappClient(
            api_token=self._settings.MARKETAPP_API_TOKEN,
            timeout=self._settings.MARKETAPP_TIMEOUT_SECONDS,
        ) as client:
            if product is ProductType.STARS:
                if not 50 <= quantity <= 1_000_000:
                    raise ValueError("Количество Stars должно быть от 50 до 1 000 000")
                response = await client.get_stars_prices(StarsPriceBody(quantity=quantity))
                ton = self._positive_decimal(response, "gram", "ton")
                usdt = self._positive_decimal(response, "usd")
            else:
                if quantity not in {3, 6, 12}:
                    raise ValueError("Срок Premium должен быть 3, 6 или 12 месяцев")
                response = await client.get_premium_price()
                option = getattr(response, f"months{quantity}", None)
                if option is None:
                    raise RuntimeError("Marketapp did not return this Premium tariff")
                ton = self._positive_decimal(option, "gram", "ton")
                usdt = self._positive_decimal(option, "usd")

        result = {Currency.TON: ton, Currency.USDT: usdt}
        self._cache[key] = (now, result)
        return result

    @staticmethod
    def _with_fixed_markup(base: Decimal, currency: Currency) -> Decimal:
        if currency is Currency.TON:
            numerator = TON_MARKUP_NUMERATOR
            denominator = TON_MARKUP_DENOMINATOR
            quantum = Decimal("0.000000001")
        else:
            numerator = USDT_MARKUP_NUMERATOR
            denominator = USDT_MARKUP_DENOMINATOR
            quantum = Decimal("0.000001")
        total = base * (Decimal(1) + numerator / denominator)
        return total.quantize(quantum, rounding=ROUND_UP)

    async def calculate(
        self,
        product: ProductType,
        currency: Currency,
        *,
        stars_amount: int | None = None,
        premium_months: int | None = None,
    ) -> Decimal:
        base = await self._base_prices(
            product,
            stars_amount=stars_amount,
            premium_months=premium_months,
        )
        return self._with_fixed_markup(base[currency], currency)
