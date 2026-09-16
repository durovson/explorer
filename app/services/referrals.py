from app.models.entities import ReferralStats
from app.repositories.users import UserRepository


class ReferralService:
    """Referral attribution with direct per-order rewards; no user balance exists."""

    def __init__(self, users: UserRepository):
        self._users = users

    async def assign(self, referred_id: int, referrer_id: int) -> bool:
        if referred_id == referrer_id or referrer_id <= 0:
            return False
        return await self._users.assign_referrer(referred_id, referrer_id)

    async def stats(self, telegram_id: int) -> ReferralStats:
        return await self._users.referral_stats(telegram_id)
