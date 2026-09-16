from app.database import SupabaseDatabase
from app.models.entities import ReferralStats, User


class UserRepository:
    def __init__(self, database: SupabaseDatabase):
        self._db = database

    async def upsert(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> User:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
        }
        response = await self._db.run(
            lambda client: (
                client.table("users")
                .upsert(payload, on_conflict="telegram_id")
                .execute()
            )
        )
        return User.model_validate(response.data[0])

    async def get(self, telegram_id: int) -> User | None:
        response = await self._db.run(
            lambda client: (
                client.table("users")
                .select("*")
                .eq("telegram_id", telegram_id)
                .limit(1)
                .execute()
            )
        )
        return User.model_validate(response.data[0]) if response.data else None

    async def assign_referrer(self, referred_id: int, referrer_id: int) -> bool:
        response = await self._db.rpc(
            "assign_referrer_once",
            {"p_referred_id": referred_id, "p_referrer_id": referrer_id},
        )
        return bool(response.data)

    async def referral_stats(self, telegram_id: int) -> ReferralStats:
        response = await self._db.rpc("referral_stats", {"p_user_id": telegram_id})
        data = response.data[0] if response.data else {}
        return ReferralStats.model_validate(data)
