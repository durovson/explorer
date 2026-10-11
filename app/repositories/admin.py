from app.database import SupabaseDatabase
from app.models.entities import AdminStats


class AdminRepository:
    def __init__(self, database: SupabaseDatabase):
        self._db = database

    async def stats(self) -> AdminStats:
        response = await self._db.rpc("admin_order_stats", {})
        return AdminStats.model_validate(response.data[0] if response.data else {})
