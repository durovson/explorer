from dataclasses import dataclass

from app.services.admin import AdminService
from app.services.fragment import FragmentService
from app.services.marketapp import MarketappService
from app.services.orders import OrderService
from app.services.payments import PaymentService
from app.services.referrals import ReferralService
from app.services.users import UserService


@dataclass(frozen=True, slots=True)
class Services:
    users: UserService
    orders: OrderService
    payments: PaymentService
    fragment: FragmentService
    marketapp: MarketappService
    referrals: ReferralService
    admin: AdminService
