from __future__ import annotations

from collections import OrderedDict
from time import monotonic

from app.database import SupabaseDatabase
from app.models.entities import ReferralStats, User

_USER_CACHE_TTL_SECONDS = 300.0
_USER_CACHE_MAX_ENTRIES = 5_000


class UserRepository:
    def __init__(self, database: SupabaseDatabase):
        self._db = database
        self._cache: OrderedDict[int, tuple[float, User]] = OrderedDict()

    def _cached(self, telegram_id: int) -> User | None:
        item = self._cache.get(telegram_id)
        if item is None:
            return None
        cached_at, user = item
        if monotonic() - cached_at >= _USER_CACHE_TTL_SECONDS:
            self._cache.pop(telegram_id, None)
            return None
        self._cache.move_to_end(telegram_id)
        return user

    def _remember(self, user: User) -> User:
        self._cache[user.telegram_id] = (monotonic(), user)
        self._cache.move_to_end(user.telegram_id)
        while len(self._cache) > _USER_CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        return user

    async def upsert(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> User:
        # IMPORTANT: never UPSERT a partial profile. PostgreSQL's conflict
        # update can reset the saved language to its default on every message.
        existing = self._cached(telegram_id)
        if existing is None:
            existing = await self.get(telegram_id)
        if (
            existing is not None
            and existing.username == username
            and existing.first_name == first_name
        ):
            return existing
        payload = {"username": username, "first_name": first_name}
        if existing is None:
            payload["telegram_id"] = telegram_id
            response = await self._db.run(
                lambda client: client.table("users").insert(payload).execute()
            )
        else:
            response = await self._db.run(
                lambda client: client.table("users").update(payload)
                .eq("telegram_id", telegram_id).execute()
            )
        return self._remember(User.model_validate(response.data[0]))

    async def set_language(self, telegram_id: int, language: str) -> User:
        if language not in ("ru", "en"):
            raise ValueError("Unsupported language")
        response = await self._db.run(
            lambda client: client.table("users").update(
                {"language": language}
            ).eq("telegram_id", telegram_id).execute()
        )
        if not response.data:
            raise ValueError("User not found")
        return self._remember(User.model_validate(response.data[0]))

    async def get(self, telegram_id: int) -> User | None:
        cached = self._cached(telegram_id)
        if cached is not None:
            return cached
        response = await self._db.run(
            lambda client: (
                client.table("users")
                .select("*")
                .eq("telegram_id", telegram_id)
                .limit(1)
                .execute()
            )
        )
        if not response.data:
            return None
        return self._remember(User.model_validate(response.data[0]))

    async def assign_referrer(self, referred_id: int, referrer_id: int) -> bool:
        response = await self._db.rpc(
            "assign_referrer_once",
            {"p_referred_id": referred_id, "p_referrer_id": referrer_id},
        )
        assigned = bool(response.data)
        if assigned:
            self._cache.pop(referred_id, None)
        return assigned

    async def referral_stats(self, telegram_id: int) -> ReferralStats:
        response = await self._db.rpc("referral_stats_v2", {"p_user_id": telegram_id})
        data = response.data[0] if response.data else {}
        return ReferralStats.model_validate(data)
