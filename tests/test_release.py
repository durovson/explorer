import asyncio
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
from app.services.pricing import PriceService
from app.services.fragment import FragmentService
from app.core.enums import Currency, ProductType
from app.keyboards.menu import settings_keyboard, orders_keyboard
from app.utils.emoji import COMPLETE

class ReleaseTests(unittest.TestCase):
    def test_inclusive_fee_and_four_places(self):
        for currency in Currency:
            for base in map(Decimal, ['.751234567','1','1.0229388','100.123456789']):
                total=PriceService._with_fixed_markup(base,currency)
                self.assertLessEqual(total,base*Decimal('1.05'))
                self.assertGreaterEqual(total,base)
                self.assertEqual(total.as_tuple().exponent,-4)

    def test_hidden_documents_and_no_duplicate_navigation_emoji(self):
        buttons=[b for row in settings_keyboard().inline_keyboard for b in row]
        self.assertNotIn('settings:documents',[b.callback_data for b in buttons])
        first=orders_keyboard([],0,True,2)
        second=orders_keyboard([],1,False,2)
        self.assertIn('1/2',[b.text for row in first.inline_keyboard for b in row])
        self.assertIn('2/2',[b.text for row in second.inline_keyboard for b in row])
        self.assertNotIn('➡️',[b.text for row in first.inline_keyboard for b in row])
        self.assertEqual(COMPLETE,'5260416304224936047')

    def test_recipient_preflight_rejects_premium_frozen_and_unavailable(self):
        service=FragmentService(Mock())
        for product,data in [(ProductType.PREMIUM,{'has_premium':True}),
                             (ProductType.STARS,{'frozen':True}),
                             (ProductType.STARS,{'can_receive_stars':False}),
                             (ProductType.STARS,{})]:
            client=Mock(search_stars_recipient=AsyncMock(return_value=data),search_premium_recipient=AsyncMock(return_value=data))
            with patch.object(service,'_client',return_value=client):
                with self.assertRaises((ValueError,RuntimeError)):
                    asyncio.run(service.user_info('@alice_user',product))
        client=Mock(search_stars_recipient=AsyncMock(return_value={'name':'Alice','photo':''}))
        with patch.object(service,'_client',return_value=client):
            self.assertEqual(asyncio.run(service.user_info('@alice_user',ProductType.STARS))['name'],'Alice')
