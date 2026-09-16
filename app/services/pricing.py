from decimal import ROUND_UP, Decimal

from app.config import Settings
from app.core.enums import Currency, ProductType


class PriceService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def calculate(
        self,
        product: ProductType,
        currency: Currency,
        *,
        stars_amount: int | None = None,
        premium_months: int | None = None,
    ) -> Decimal:
        quantum = (
            Decimal("0.000000001") if currency is Currency.TON else Decimal("0.000001")
        )
        if product is ProductType.STARS:
            if stars_amount is None or not 50 <= stars_amount <= 1_000_000:
                raise ValueError("Количество Stars должно быть от 50 до 1 000 000")
            rate = (
                self._settings.STARS_TON_PER_UNIT
                if currency is Currency.TON
                else self._settings.STARS_USDT_PER_UNIT
            )
            return (rate * stars_amount).quantize(quantum, rounding=ROUND_UP)
        if premium_months not in {3, 6, 12}:
            raise ValueError("Срок Premium должен быть 3, 6 или 12 месяцев")
        value: Decimal = getattr(
            self._settings, f"PREMIUM_{premium_months}_{currency.value}"
        )
        return value.quantize(quantum, rounding=ROUND_UP)
