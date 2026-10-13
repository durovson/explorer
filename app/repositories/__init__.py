from dataclasses import dataclass

from app.database import SupabaseDatabase
from app.repositories.admin import AdminRepository
from app.repositories.orders import OrderRepository
from app.repositories.payments import PaymentRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class Repositories:
    users: UserRepository
    orders: OrderRepository
    payments: PaymentRepository
    admin: AdminRepository

    @classmethod
    def build(cls, database: SupabaseDatabase) -> "Repositories":
        return cls(
            users=UserRepository(database),
            orders=OrderRepository(database),
            payments=PaymentRepository(database),
            admin=AdminRepository(database),
        )
