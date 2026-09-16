from dataclasses import dataclass

from app.database import SupabaseDatabase
from app.repositories.admin import AdminRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class Repositories:
    users: UserRepository
    orders: OrderRepository
    admin: AdminRepository

    @classmethod
    def build(cls, database: SupabaseDatabase) -> "Repositories":
        return cls(
            users=UserRepository(database),
            orders=OrderRepository(database),
            admin=AdminRepository(database),
        )
