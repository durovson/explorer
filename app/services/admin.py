from uuid import UUID

from app.config import Settings
from app.models.entities import AdminStats, Order
from app.repositories.admin import AdminRepository
from app.repositories.orders import OrderRepository


class AdminService:
    def __init__(
        self, settings: Settings, admin: AdminRepository, orders: OrderRepository
    ):
        self._settings = settings
        self._admin = admin
        self._orders = orders

    def require(self, user_id: int) -> None:
        if user_id not in self._settings.admin_ids:
            raise PermissionError("Administrator access required")

    async def stats(self, user_id: int) -> AdminStats:
        self.require(user_id)
        return await self._admin.stats()

    async def approve_retry(self, user_id: int, order_id: UUID, reason: str) -> Order:
        self.require(user_id)
        if len(reason.strip()) < 5:
            raise ValueError("Укажите причину длиной не менее 5 символов")
        order = await self._orders.approve_retry(order_id, user_id, reason.strip())
        if order is None:
            raise ValueError("Заказ нельзя безопасно вернуть в очередь")
        return order
