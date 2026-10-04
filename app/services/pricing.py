from decimal import ROUND_UP, Decimal

from app.config import Settings
from app.core.enums import Currency, ProductType


class PriceService:
    def __init__(self, settings: Settings):
        self._settings = settings

    @staticmethod
    def _quantum(currency: Currency) -> Decimal:
        return Decimal("0.000000001") if currency is Currency.TON else Decimal("0.000001")

    def calculate(
        self,
        product: ProductType,
        currency: Currency,
        *,
        stars_amount: int | None = None,
        premium_months: int | None = None,
        gram_amount: Decimal | None = None,
        provider_price_gram: Decimal | None = None,
    ) -> Decimal:
        quantum = self._quantum(currency)
        if product is ProductType.STARS:
            if stars_amount is None or not 50 <= stars_amount <= 1_000_000:
                raise ValueError("Количество Stars должно быть от 50 до 1 000 000")
            rate = (
                self._settings.STARS_TON_PER_UNIT
                if currency is Currency.TON
                else self._settings.STARS_USDT_PER_UNIT
            )
            return (rate * stars_amount).quantize(quantum, rounding=ROUND_UP)
        if product is ProductType.PREMIUM:
            if premium_months not in {3, 6, 12}:
                raise ValueError("Срок Premium должен быть 3, 6 или 12 месяцев")
            value: Decimal = getattr(
                self._settings, f"PREMIUM_{premium_months}_{currency.value}"
            )
            return value.quantize(quantum, rounding=ROUND_UP)
        if product is ProductType.GRAM:
            if currency is not Currency.TON:
                raise ValueError("Пополнение GRAM сейчас оплачивается только TON")
            if (
                gram_amount is None
                or gram_amount != gram_amount.to_integral_value()
                or not (
                    self._settings.MARKETAPP_GRAM_MIN
                    <= gram_amount
                    <= self._settings.MARKETAPP_GRAM_MAX
                )
            ):
                raise ValueError(
                    f"GRAM должен быть целым числом от {self._settings.MARKETAPP_GRAM_MIN} "
                    f"до {self._settings.MARKETAPP_GRAM_MAX}"
                )
            return (gram_amount * self._settings.MARKETAPP_GRAM_MARKUP).quantize(
                quantum, rounding=ROUND_UP
            )
        if product is ProductType.NFT_RENT:
            if currency is not Currency.TON:
                raise ValueError("Аренда NFT сейчас оплачивается только TON")
            if provider_price_gram is None or provider_price_gram <= 0:
                raise ValueError("Marketapp не вернул корректную цену аренды")
            return (provider_price_gram * self._settings.MARKETAPP_RENT_MARKUP).quantize(
                quantum, rounding=ROUND_UP
            )
        raise ValueError(f"Неподдерживаемый товар: {product}")
