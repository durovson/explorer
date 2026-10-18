from __future__ import annotations

import unittest
from unittest.mock import AsyncMock
from decimal import Decimal

from app.core.enums import Currency
from app.keyboards.menu import (
    home_keyboard, language_keyboard, orders_keyboard, product_options,
    recipient_keyboard, settings_keyboard,
)
from app.models.entities import User
from app.repositories.users import UserRepository
from app.services.pricing import PriceService
from app.utils.i18n import restore_language, select_language, tr


class BotUiTests(unittest.TestCase):
    def test_language_context_and_restore(self):
        token = select_language("en")
        try:
            self.assertEqual(tr("Назад", "Back"), "Back")
            self.assertEqual(settings_keyboard().inline_keyboard[-1][0].text, "Back")
            self.assertEqual(language_keyboard().inline_keyboard[1][0].text, "English ✓")
            self.assertEqual(home_keyboard("https://t.me/not_jammm").inline_keyboard[1][0].text, "Purchases")
        finally:
            restore_language(token)
        self.assertEqual(tr("Назад", "Back"), "Назад")

    def test_language_persisted_in_user_model(self):
        self.assertEqual(User(telegram_id=1).language, "ru")
        self.assertEqual(User(telegram_id=1, language="en").language, "en")

    def test_profile_lookup_preserves_language(self):
        repo = UserRepository(database=object())
        repo.get = AsyncMock(
            return_value=User(telegram_id=11, username="customer", first_name="Customer", language="en")
        )
        preserved = __import__("asyncio").run(repo.upsert(11, "customer", "Customer"))
        self.assertEqual(preserved.language, "en")

    def test_recipient_and_custom_prices(self):
        keys = recipient_keyboard("bob").inline_keyboard
        self.assertEqual([button.callback_data for button in keys[0]], ["recipient:self", "recipient:other"])
        prices = {50: "0.590123456", 100: "1.190000001"}
        keys = product_options("STARS", prices).inline_keyboard
        self.assertIn("0.590123456", keys[0][0].text)
        self.assertEqual(keys[0][0].callback_data, "amount:50")
        self.assertEqual(keys[-1][0].callback_data, "buy:STARS")

    def test_prices_preserve_nanoton_precision(self):
        self.assertEqual(
            PriceService._with_fixed_markup(Decimal("1.0229388"), Currency.TON),
            Decimal("1.076900000"),
        )
        self.assertEqual(
            PriceService._with_fixed_markup(Decimal("1"), Currency.TON).as_tuple().exponent,
            -9,
        )
        self.assertEqual(
            PriceService._with_fixed_markup(Decimal("1"), Currency.USDT).as_tuple().exponent,
            -6,
        )


if __name__ == "__main__":
    unittest.main()
